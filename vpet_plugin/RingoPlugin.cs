using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using VPet_Simulator.Core;
using VPet_Simulator.Windows.Interface;
using Work = VPet_Simulator.Core.GraphHelper.Work;
using GraphType = VPet_Simulator.Core.GraphInfo.GraphType;
using AnimatType = VPet_Simulator.Core.GraphInfo.AnimatType;

namespace RingoVPet;

public sealed class RingoPlugin : MainPlugin
{
    private TcpListener? _listener;
    private CancellationTokenSource? _stop;
    private Task? _server;
    private bool _moving;
    private int _menuIndex;

    public RingoPlugin(IMainWindow window) : base(window) { }
    public override string PluginName => "RingoVPet";

    public override void GameLoaded()
    {
        if (_listener is not null) return;
        _stop = new CancellationTokenSource();
        _listener = new TcpListener(IPAddress.Loopback, 17889);
        try
        {
            _listener.Start();
            _server = ServeAsync(_stop.Token);
        }
        catch (SocketException)
        {
            Console.Error.WriteLine("RingoVPet: 127.0.0.1:17889 is already in use");
            _listener = null;
            _stop.Dispose();
            _stop = null;
        }
    }

    public override void EndGame()
    {
        _stop?.Cancel();
        _listener?.Stop();
        _listener = null;
        _stop?.Dispose();
        _stop = null;
        if (MW.Dispatcher.CheckAccess()) EndMove();
        else MW.Dispatcher.Invoke(EndMove);
    }

    private async Task ServeAsync(CancellationToken stop)
    {
        while (!stop.IsCancellationRequested && _listener is not null)
        {
            TcpClient client;
            try { client = await _listener.AcceptTcpClientAsync(stop); }
            catch (OperationCanceledException) { break; }
            catch (ObjectDisposedException) { break; }
            // One controller at a time, so a second client cannot steal an active move.
            using (client)
            {
                try { await HandleClientAsync(client, stop); }
                catch (IOException) { }
                catch (SocketException) { }
                catch (OperationCanceledException) { }
                finally
                {
                    try { MW.Dispatcher.Invoke(EndMove); }
                    catch (TaskCanceledException) { }
                    catch (InvalidOperationException) { }
                }
            }
        }
    }

    private async Task HandleClientAsync(TcpClient client, CancellationToken stop)
    {
        client.ReceiveTimeout = 5000;
        client.SendTimeout = 5000;
        using var stream = client.GetStream();
        using var input = new StreamReader(stream, Encoding.UTF8, leaveOpen: true);
        using var output = new StreamWriter(stream, new UTF8Encoding(false), leaveOpen: true) { AutoFlush = true };
        while (!stop.IsCancellationRequested)
        {
            using var idle = CancellationTokenSource.CreateLinkedTokenSource(stop);
            idle.CancelAfter(TimeSpan.FromSeconds(5));
            string? line;
            try { line = await input.ReadLineAsync(idle.Token); }
            catch (OperationCanceledException) { break; }
            if (line is null) break;
            if (line.Length > 4096)
            {
                await output.WriteLineAsync("{\"command\":\"\",\"ok\":false,\"error\":\"request_too_large\"}");
                break;
            }
            string command = "";
            try
            {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                command = root.GetProperty("command").GetString()?.ToUpperInvariant() ?? "";
                if (root.GetProperty("version").GetInt32() != 1)
                    throw new ArgumentException("unsupported_version");
                var dx = root.TryGetProperty("dx", out var x) ? x.GetDouble() : 0;
                var dy = root.TryGetProperty("dy", out var y) ? y.GetDouble() : 0;
                var result = MW.Dispatcher.Invoke(() => Execute(command, dx, dy));
                await output.WriteLineAsync(JsonSerializer.Serialize(new { command, ok = result.ok, error = result.error }));
            }
            catch (Exception error)
            {
                await output.WriteLineAsync(JsonSerializer.Serialize(new { command, ok = false, error = error.Message }));
            }
        }
    }

    private (bool ok, string? error) Execute(string command, double dx, double dy)
    {
        var main = MW.Main;
        if (main is null) return (false, "game_not_ready");
        var window = MW as Window;
        switch (command)
        {
            case "PING": return (true, null);
            case "SUMMON":
                if (window is null) return (false, "window_unavailable");
                window.Show();
                window.Visibility = Visibility.Visible;
                return (true, null);
            case "FAREWELL":
                if (window is null) return (false, "window_unavailable");
                EndMove();
                window.Hide();
                return (true, null);
            case "STUDY":
                var work = new List<Work>();
                var study = new List<Work>();
                var play = new List<Work>();
                main.WorkList(out work, out study, out play);
                var task = study.FirstOrDefault(x => x.Type == Work.WorkType.Study);
                if (task is null) return (false, "no_study_task");
                if (main.State == Main.WorkingState.Work && main.NowWork?.Name == task.Name)
                    return (true, null);
                return main.StartWork(task) ? (true, null) : (false, "study_unavailable");
            case "MOVE_START":
                if (window?.IsVisible != true) return (false, "pet_hidden");
                if (_moving) return (true, null);
                _moving = true;
                ShowRaised();
                return (true, null);
            case "MOVE_DELTA":
                if (!_moving) return (false, "move_not_started");
                if (!double.IsFinite(dx) || !double.IsFinite(dy) || Math.Abs(dx) > 80 || Math.Abs(dy) > 80)
                    return (false, "invalid_delta");
                if (window is null) return (false, "window_unavailable");
                // MoveWindows uses game coordinates; ZoomRatio converts screen pixels.
                var left = Math.Clamp(window.Left + dx, SystemParameters.VirtualScreenLeft,
                    SystemParameters.VirtualScreenLeft + SystemParameters.VirtualScreenWidth - window.ActualWidth);
                var top = Math.Clamp(window.Top + dy, SystemParameters.VirtualScreenTop,
                    SystemParameters.VirtualScreenTop + SystemParameters.VirtualScreenHeight - window.ActualHeight);
                MW.Core.Controller!.MoveWindows((left - window.Left) / MW.Core.Controller.ZoomRatio,
                    (top - window.Top) / MW.Core.Controller.ZoomRatio);
                return (true, null);
            case "MOVE_END":
                EndMove();
                return (true, null);
            case "PLAY_DEAD":
                main.DisplaySleep(true);
                return (true, null);
            case "PET":
                main.DisplayTouchHead();
                return (true, null);
            case "FEED":
                var food = MW.Foods.FirstOrDefault(x => (x.Type == Food.FoodType.Meal || x.Type == Food.FoodType.Snack)
                    && x.ImageSource is not null && !x.IsOverLoad());
                if (food is null) return (false, "no_food_available");
                MW.DisplayFoodAnimation(food.GetGraph(), food.ImageSource!);
                MW.TakeItem(food);
                return (true, null);
            case "PANEL_TOGGLE":
                if (main.ToolBar.Visibility == Visibility.Visible)
                {
                    main.ToolBar.Visibility = Visibility.Collapsed;
                    return (true, null);
                }
                main.ToolBar.Show();
                return (true, null);
            case "PANEL_NEXT": return SelectMenu(1);
            case "PANEL_PREV": return SelectMenu(-1);
            default: return (false, "unsupported_command");
        }
    }

    private (bool ok, string? error) SelectMenu(int step)
    {
        var bar = MW.Main.ToolBar;
        if (bar.Visibility != Visibility.Visible) return (false, "panel_closed");
        MenuItem[] items = [bar.MenuFeed, bar.MenuInteract, bar.MenuStudy,
                            bar.MenuPlay, bar.MenuWork, bar.MenuDIY, bar.MenuSetting];
        items[_menuIndex].IsSubmenuOpen = false;
        _menuIndex = (_menuIndex + step + items.Length) % items.Length;
        items[_menuIndex].Focus();
        items[_menuIndex].IsSubmenuOpen = true;
        return (true, null);
    }

    private void EndMove()
    {
        if (!_moving) return;
        _moving = false;
        MW.Main?.Display(GraphType.Raised_Static, AnimatType.C_End,
            new Action(() => MW.Main?.DisplayToNomal()));
    }

    private void ShowRaised()
    {
        if (!_moving) return;
        MW.Main?.Display(GraphType.Raised_Static, AnimatType.B_Loop,
            new Action(ShowRaised));
    }
}
