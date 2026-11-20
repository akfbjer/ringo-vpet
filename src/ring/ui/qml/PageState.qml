pragma Singleton
import QtQml

QtObject {
    // Lives for the QML engine lifetime, independently of Loader pages.
    property var values: ({})

    function save(page, options) {
        var next = Object.assign({}, values)
        next[page] = options
        values = next
    }
}
