from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt


class DeviceModel(QAbstractListModel):
    """Stable delegates: telemetry updates never recreate buttons or lose focus."""
    ROLE = Qt.ItemDataRole.UserRole + 1
    NAME_ROLE = ROLE + 1
    ADDRESS_ROLE = ROLE + 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def roleNames(self):
        return {self.ROLE: b"device", self.NAME_ROLE: b"name", self.ADDRESS_ROLE: b"address"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid():
            row = self.rows[index.row()]
            if role == self.ROLE:
                return row
            if role == self.NAME_ROLE:
                return row["name"]
            if role == self.ADDRESS_ROLE:
                return row["address"]

    def update(self, devices):
        devices = [dict(d, address=str(d["address"]), name=str(d.get("name", ""))) for d in devices]
        addresses = {d["address"] for d in devices}
        for row in range(len(self.rows)-1, -1, -1):
            if self.rows[row]["address"] not in addresses:
                self.beginRemoveRows(QModelIndex(), row, row)
                self.rows.pop(row)
                self.endRemoveRows()
        for row, device in enumerate(devices):
            existing = next((i for i, d in enumerate(self.rows) if d["address"] == device["address"]), None)
            if existing is None:
                self.beginInsertRows(QModelIndex(), row, row)
                self.rows.insert(row, device)
                self.endInsertRows()
            else:
                if existing != row:
                    self.beginMoveRows(QModelIndex(), existing, existing, QModelIndex(), row)
                    self.rows.insert(row, self.rows.pop(existing))
                    self.endMoveRows()
                if self.rows[row] != device:
                    self.rows[row] = device
                    index = self.index(row)
                    self.dataChanged.emit(index, index, [self.ROLE, self.NAME_ROLE, self.ADDRESS_ROLE])
