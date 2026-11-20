"""Ringo multimodal acquisition, bounded previews and full-fidelity recording."""
import asyncio
from collections import deque
from datetime import datetime
import struct
import time
from ring.drivers.ringo_protocol import IMU_START, MIC_START, decode_packet, opus_frames
from .recording import Recording
from ring.runtime.recorder import Recorder
from .audio import AudioDecoder, OrderedAudio
from .adpcm import AdpcmDecoder
from .wav_recording import WavRecording


class RingoLab:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.devices = {}
        self.recording = None
        self.last_path = self.error = ''
        self.imu_timeout = 3.0
        self.controls = set()
        self.imu_waiters = {}
        self.audio_waiters = {}
        self.audio_tasks = set()
        self.imu_tasks = set()
        self.last_imu = dict(path='', error='', count=0)
        self.audio_timeout = 3.0
        self.last_audio = dict(path='', error='', seconds=0.0)

    def device(self, address):
        if address not in self.devices:
            self.devices[address] = dict(counts={}, latest={}, seen={}, plots={}, buttons=deque(maxlen=50),
                imu_writer=None, imu_saving=False, imu_path='', imu_count=0, imu_error='', fragments={}, decoder=None, audio_error='', audio_unavailable=False, audio_encoding='', audio_writer=None, audio_saving=False, audio_path='', audio_seconds=0.0, gaps=0, sequences={}, request='尚未发送控制', connected=False)
        return self.devices[address]

    def record(self, address, event):
        if self.recording:
            self.recording.submit(dict(address=address, received_ns=time.monotonic_ns(), unix_ns=time.time_ns(), **event))

    def connection(self, address, connected):
        d = self.device(address)
        if d['connected'] == connected:
            return
        d['connected'] = connected
        waiter = self.imu_waiters.get(address)
        if not connected and waiter and not waiter.done():
            waiter.set_exception(ConnectionError('等待 IMU 数据期间设备断开'))
        if not connected:
            audio_waiter = self.audio_waiters.get(address)
            if audio_waiter and not audio_waiter.done():
                audio_waiter.set_exception(ConnectionError('录音启动期间设备断开'))
            self.end_audio(address, '设备断开，录音已提前结束')
            self.end_imu_recording(address, '设备断开，IMU 录制已提前结束')
        self.record(address, dict(type='connection', connected=connected))
        d['fragments'].clear()
        d['sequences'].clear()
        d['seen'].clear()
        d['plots'].clear()
        d['latest'].clear()
        if d['decoder']:
            d['decoder'].close()
            d['decoder'] = None
        d['audio_error'] = ''
        d['audio_unavailable'] = False
        d['audio_encoding'] = ''
        d['request'] = '连接已变化，请重新选择采集流'

    def plot(self, d, name, values):
        d['plots'].setdefault(name, deque(maxlen=240)).extend(values)

    def receive(self, address, raw):
        self.record(address, dict(type='rx', hex=bytes(raw).hex()))
        d = self.device(address)
        try:
            event = decode_packet(raw)
            kind = event['kind']
            d['counts'][kind] = d['counts'].get(kind, 0) + 1
            d['seen'][kind] = time.monotonic()
            if 'seq' in event and kind != 'mic':
                key = (event['cmd'], event['subcmd'])
                previous = d['sequences'].get(key)
                if previous is not None and event['seq'] != (previous + 1) % 65536:
                    d['gaps'] += 1
                    self.record(address, dict(type='sequence_gap', stream=kind, previous=previous, current=event['seq']))
                d['sequences'][key] = event['seq']
            if kind == 'imu':
                waiter = self.imu_waiters.get(address)
                if event['frames'] and waiter and not waiter.done():
                    waiter.set_result(True)
                for frame in event['frames']:
                    for name, value in zip(('ax', 'ay', 'az', 'gx', 'gy', 'gz'), frame['values']):
                        self.plot(d, name, [value])
            elif kind == 'button':
                d['buttons'].appendleft(dict(label=event['label'], seq=event['seq'], uptime_ms=event['uptime_ms']))
            elif kind == 'ppg_raw':
                for name, values in event['channels'].items():
                    self.plot(d, name, values)
            elif kind == 'ppg':
                self.plot(d, 'hr', [event['hr']])
            elif kind == 'mic':
                self.microphone(address, d, event)
            d['latest'][kind] = {k: v for k, v in event.items() if k not in ('frames', 'payload', 'channels')}
            self.record(address, dict(type='decoded', **event))
        except (ValueError, IndexError, struct.error) as exc:
            if raw[:1] == b'\x20':
                d['audio_error'] = f'音频包无效：{exc}'
            d['counts']['invalid'] = d['counts'].get('invalid', 0) + 1
            self.record(address, dict(type='decode_error', error=str(exc)))

    def microphone(self, address, d, event):
        encoding = event['encoding']
        if d['audio_encoding'] and d['audio_encoding'] != encoding:
            raise ValueError('音频编码在采集中变化，请重新启动麦克风')
        d['audio_encoding'] = encoding
        decoder = d['decoder']
        if decoder and ((event['seq'] - decoder.next_seq) % 65536 >= 32768 or event['seq'] in decoder.pending):
            return
        parts = d['fragments']
        key = (event['seq'], event['uptime_ms'])
        now = time.monotonic()
        for old in list(parts):
            if now - parts[old]['time'] > 2 or len(parts) >= 16 and old != key:
                del parts[old]
                d['gaps'] += 1
                d['audio_error'] = '音频分片丢失，WAV 可能不完整'
        block = parts.setdefault(key, dict(time=now, count=event['frag_count'], chunks={}))
        index, chunk = event['frag_idx'], bytes.fromhex(event['payload'])
        if block['count'] != event['frag_count'] or index in block['chunks'] and block['chunks'][index] != chunk:
            del parts[key]
            raise ValueError('conflicting microphone fragments')
        block['chunks'][index] = chunk
        self.plot(d, 'audio_bytes', [len(chunk)])
        if len(block['chunks']) != block['count']:
            return
        data = b''.join(block['chunks'][i] for i in range(block['count']))
        del parts[key]
        if encoding == 'opus':
            opus_frames(data)
        self.record(address, dict(type=encoding, seq=key[0], uptime_ms=key[1], hex=data.hex()))
        if not d['decoder'] and not d['audio_unavailable']:
            try:
                d['decoder'] = OrderedAudio(AdpcmDecoder() if encoding == 'adpcm' else AudioDecoder())
            except OSError as exc:
                d['audio_unavailable'] = True
                d['audio_error'] = str(exc)
                waiter = self.audio_waiters.get(address)
                if waiter and not waiter.done():
                    waiter.set_exception(RuntimeError(f'录音解码不可用：{exc}'))
        if d['decoder']:
            self.accept_audio(address, d['decoder'].push(key[0], key[1], data, now))

    def accept_audio(self, address, results):
        d = self.device(address)
        for seq, uptime, samples, error in results:
            if samples is None:
                d['gaps'] += 1
                d['audio_error'] = error
                self.record(address, dict(type='audio_gap', seq=seq, error=error))
                continue
            self.plot(d, 'pcm', [max(abs(v) for v in samples[i:i+80]) / 32768 for i in range(0, len(samples), 80)])
            self.record(address, dict(type='pcm', seq=seq, uptime_ms=uptime, sample_rate=16000, samples=samples))
            writer = d['audio_writer']
            if writer:
                writer.submit(samples)
                waiter = self.audio_waiters.get(address)
                if waiter and not waiter.done():
                    waiter.set_result(True)

    def reset_audio(self, address):
        d = self.device(address)
        if d['decoder']:
            d['decoder'].close()
        d['decoder'] = None
        d['fragments'].clear()
        d['audio_error'] = ''
        d['audio_unavailable'] = False
        d['audio_encoding'] = ''
        for name in ('pcm', 'audio_bytes'):
            d['plots'].pop(name, None)

    def end_audio(self, address, reason=''):
        d = self.device(address)
        if not d['audio_writer']:
            return None
        if d['decoder']:
            self.accept_audio(address, d['decoder'].drain(time.monotonic(), force=True))
        if d['fragments']:
            d['audio_error'] = '存在未收齐的音频分片，WAV 不完整'
        writer, d['audio_writer'] = d['audio_writer'], None
        d['audio_saving'] = True
        error = reason or d['audio_error']
        async def finish():
            try:
                await asyncio.to_thread(writer.close)
                d['audio_seconds'] = writer.samples / 16000
                d['audio_error'] = writer.error or error
                self.last_audio = dict(path=str(writer.path), error=d['audio_error'], seconds=d['audio_seconds'])
            finally:
                d['audio_saving'] = False
        task = asyncio.create_task(finish())
        self.audio_tasks.add(task)
        task.add_done_callback(self.audio_tasks.discard)
        return task

    async def start_audio(self, address, ring):
        d = self.device(address)
        if d['audio_writer'] or d['audio_saving']:
            raise RuntimeError('请先结束当前录音并等待保存完成')
        # Stop the old encoder session and discard its queued notifications.
        await ring.write(b'\x20\x01')
        await asyncio.sleep(.2)
        self.reset_audio(address)
        # Codec is selected from the first notification, not from a version guess.
        path = self.data_dir / (datetime.now().strftime('ringo-audio-%Y%m%d-%H%M%S-%f') + '.wav')
        try:
            d['audio_writer'] = WavRecording(path)
        except BaseException:
            self.reset_audio(address)
            raise
        d['audio_path'], d['audio_seconds'] = str(path), 0.0
        d['request'] = '正在启动录音，等待有效音频…'
        waiter = asyncio.get_running_loop().create_future()
        self.audio_waiters[address] = waiter
        try:
            await ring.write(b'\x2c\x00\x00')
            await ring.write(MIC_START)
            try:
                await asyncio.wait_for(waiter, self.audio_timeout)
            except TimeoutError as exc:
                raise RuntimeError('录音启动失败：未收到可解码音频。' + (d['audio_error'] or '请检查充电状态、麦克风占用和通知链路')) from exc
            d['request'] = '录音中 · WAV / 16 kHz / 单声道'
        except BaseException:
            try:
                await ring.write(b'\x20\x01')
            finally:
                task = self.end_audio(address, '录音启动失败，文件可能为空或不完整')
                if task:
                    await asyncio.shield(task)
            raise
        finally:
            self.audio_waiters.pop(address, None)
            if not waiter.done():
                waiter.cancel()

    async def stop_audio(self, address, ring):
        if not self.device(address)['audio_writer']:
            raise RuntimeError('当前设备没有进行中的录音')
        reason = ''
        try:
            await ring.write(b'\x20\x01')
            await asyncio.sleep(.2)  # Allow already queued notifications to arrive.
        except BaseException:
            reason = '麦克风停止失败，已保存收到的音频'
            raise
        finally:
            task = self.end_audio(address, reason)
            if task:
                await asyncio.shield(task)
        d = self.device(address)
        d['request'] = d['audio_error'] or '录音已结束，WAV 已保存'

    def is_imu_recording(self, address):
        return bool(self.devices.get(address, {}).get('imu_writer'))

    def feed_imu(self, sample):
        writer = self.device(sample['address'])['imu_writer']
        if writer:
            writer.submit(sample)

    def end_imu_recording(self, address, reason=''):
        d = self.device(address)
        writer, d['imu_writer'] = d['imu_writer'], None
        if not writer:
            return None
        d['imu_saving'] = True
        if reason and not writer.error:
            writer.error = reason
        async def finish():
            try:
                try:
                    await asyncio.to_thread(writer.close)
                except Exception as exc:
                    writer.error = f'IMU 保存失败：{exc}'
                d['imu_count'], d['imu_error'] = writer.count, writer.error
                self.last_imu = dict(path=str(writer.path), count=writer.count, error=writer.error)
            finally:
                d['imu_saving'] = False
        task = asyncio.create_task(finish())
        self.imu_tasks.add(task)
        task.add_done_callback(self.imu_tasks.discard)
        return task

    async def start_imu_recording(self, address, ring):
        d = self.device(address)
        if d['imu_writer'] or d['imu_saving']:
            raise RuntimeError('请先结束当前 IMU 录制并等待保存完成')
        path = self.data_dir / (datetime.now().strftime('ringo-imu-%Y%m%d-%H%M%S-%f') + '.h5')
        d['imu_writer'] = Recorder(path)
        d['imu_path'], d['imu_error'], d['imu_count'] = str(path), '', 0
        try:
            await self.start_imu(address, ring)
            d['request'] = 'IMU 录制中'
        except BaseException:
            task = self.end_imu_recording(address, 'IMU 录制启动失败')
            if task:
                await asyncio.shield(task)
            raise

    async def start_imu(self, address, ring):
        d = self.device(address)
        d['request'] = '正在启动 IMU，等待有效六轴数据…'
        for kind in ('runtime', 'battery'):
            d['latest'].pop(kind, None)
        waiter = asyncio.get_running_loop().create_future()
        self.imu_waiters[address] = waiter
        try:
            await ring.write(b"\x2c\x00\x00")  # NORMAL: enable sensor notifications.
            await ring.write(IMU_START)
            await ring.write(b'\x2c\x03')  # Read-only runtime query; works even in muted TX modes.
            await ring.write(b'\x29\x01')
            try:
                await asyncio.wait_for(waiter, self.imu_timeout)
            except TimeoutError as exc:
                status = d['latest'].get('runtime', {})
                battery = d['latest'].get('battery', {})
                reasons = []
                if battery.get('charge') in (1, 2):
                    reasons.append('设备报告充电/充满：固件在充电座上拒绝传感器启动，请取下后重试')
                flags = status.get('active', 0)
                if flags & (1 << 5):
                    reasons.append('HEALTH 正在采集，占用 IMU')
                if flags & (1 << 9):
                    reasons.append('IMU 标定正在占用传感器')
                if status.get('tx_mode', 0) != 0:
                    reasons.append(f"TX mode={status['tx_mode']}，固件不发送普通传感器通知")
                if status:
                    reasons.append(f"运行态 active=0x{flags:04x}，IMU BLE 流={'开' if flags & 4 else '关'}，"
                                   f"gyro/accel={status['gyro_hz']}/{status['accel_hz']} Hz，encode={status['encode_mode']}")
                else:
                    reasons.append('未收到运行态应答，请检查固件版本与通知链路')
                raise RuntimeError('IMU 启动未确认：未收到有效数据。' + '；'.join(reasons)) from exc
            d['request'] = 'IMU 已确认：收到有效六轴数据（200 Hz / 16 g / 2000 dps 请求）'
        finally:
            self.imu_waiters.pop(address, None)
            if not waiter.done():
                waiter.cancel()

    async def control(self, address, ring, action):
        if address in self.controls:
            raise RuntimeError('请等待当前设备控制完成')
        self.controls.add(address)
        try:
            await self._control(address, ring, action)
        except Exception as exc:
            self.device(address)['request'] = str(exc)
            raise
        finally:
            self.controls.discard(address)

    async def _control(self, address, ring, action):
        d = self.device(address)
        if action == 'imu_record_start':
            await self.start_imu_recording(address, ring)
            return
        if action == 'imu_record_stop':
            task = self.end_imu_recording(address)
            if task:
                await asyncio.shield(task)
            d['request'] = d['imu_error'] or 'IMU 录制已保存，实时波形继续显示'
            return
        if action in ('imu_stop', 'stop'):
            task = self.end_imu_recording(address)
            if task:
                await asyncio.shield(task)
        if action in ('ppg_green', 'ppg_red', 'ppg_ir'):
            for name in ('green', 'red', 'ir', 'hr'):
                d['plots'].pop(name, None)
        if action == 'audio_start':
            await self.start_audio(address, ring)
            return
        if action == 'audio_stop':
            await self.stop_audio(address, ring)
            return
        if action in ('mic', 'all'):
            if d['audio_writer'] or d['audio_saving']:
                raise RuntimeError('录音进行中，请先结束录音')
            await ring.write(b'\x20\x01')
            await asyncio.sleep(.2)
            self.reset_audio(address)
            await ring.write(b'\x2c\x00\x00')
        if action in ('mic_stop', 'stop') and d['audio_writer']:
            await self.stop_audio(address, ring)
        commands = {'led_on': [b'\x28\x00\x01'], 'led_off': [b'\x28\x00\x00'],
                    'imu': [], 'imu_stop': [b'\x21\x01'],
                    'ppg_green': [b'\x24\x00\x00\x01'],
                    'ppg_red': [b'\x24\x00\x01\x01'],
                    'ppg_ir': [b'\x24\x00\x02\x01'],
                    'hrs': [b'\x24\x00\x00\x01'], 'spo2': [b'\x24\x00\x01\x01'],
                    'wear': [b'\x24\x00\x02\x01'], 'ppg_stop': [b'\x24\x01'],
                    'mic': [MIC_START], 'mic_stop': [b'\x20\x01'],
                    'all': [ b'\x24\x00\x00\x01', MIC_START],
                    'stop': [b'\x21\x01', b'\x24\x01', b'\x20\x01']}
        if action not in commands:
            raise ValueError('未知 Ringo 控制')
        if action in ('imu', 'all'):
            await self.start_imu(address, ring)
        for command in commands[action]:
            await ring.write(command)
        if action != 'imu':
            prefix = 'IMU 已收到数据；' if action == 'all' else ''
            self.device(address)['request'] = prefix + f'已发送 {action}（其余控制无固件 ACK；以实际接收为准）'

    async def toggle_record(self, devices):
        if self.recording:
            recorder, self.recording = self.recording, None
            await asyncio.to_thread(recorder.close)
            self.error = recorder.error
        else:
            if not any(d['driver'] == 'ringo' and d['connected'] for d in devices.values()):
                raise RuntimeError('请先连接 Ringo')
            path = self.data_dir / (datetime.now().strftime('ringo-%Y%m%d-%H%M%S-%f') + '.jsonl')
            self.recording = Recording(path, [dict(d) for d in devices.values() if d['driver'] == 'ringo'])
            self.last_path, self.error = str(path), ''

    def snapshot(self, devices):
        result = []
        for address, device in devices.items():
            if device['driver'] != 'ringo' or device['simulated'] or not device['connected']:
                continue
            d = self.device(address)
            result.append(dict(address=address, name=device['name'], connected=device['connected'], busy=device['busy'] or address in self.controls,
                counts=dict(d['counts']), latest=dict(d['latest']), buttons=list(d['buttons']),
                plots={k: list(v) for k, v in d['plots'].items()}, gaps=d['gaps'],
                imuRecording=d['imu_writer'] is not None, imuSaving=d['imu_saving'],
                imuPath=d['imu_path'], imuCount=d['imu_writer'].count if d['imu_writer'] else d['imu_count'],
                imuError=d['imu_writer'].error if d['imu_writer'] else d['imu_error'],
                audioError=(d['audio_writer'].error if d['audio_writer'] else '') or d['audio_error'],
                audioRecording=d['audio_writer'] is not None, audioSaving=d['audio_saving'],
                audioEncoding=d['audio_encoding'], audioPath=d['audio_path'], audioSeconds=d['audio_writer'].samples / 16000 if d['audio_writer'] else d['audio_seconds'],
                request=d['request']))
        return dict(devices=result, recording=self.recording is not None, path=self.last_path, lastAudio=dict(self.last_audio), lastIMU=dict(self.last_imu),
                    count=self.recording.count if self.recording else 0,
                    error=self.recording.error if self.recording else self.error)

    async def close(self):
        for address in self.devices:
            self.end_audio(address, '应用退出，录音已结束')
            self.end_imu_recording(address)
        if self.imu_tasks:
            await asyncio.gather(*list(self.imu_tasks))
        if self.audio_tasks:
            await asyncio.gather(*list(self.audio_tasks))
        if self.recording:
            await self.toggle_record({})
        for d in self.devices.values():
            if d['decoder']:
                d['decoder'].close()
