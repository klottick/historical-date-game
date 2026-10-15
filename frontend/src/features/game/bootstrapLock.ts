import { storageUnavailable } from "./identityState.ts"

const databaseName = "historical-date-game-bootstrap"
const storeName = "coordination"
const boundMs = 15_000

/** An IndexedDB writer is exclusive across tabs, including on HTTP origins.
 * Queue native requests continuously: an idle transaction would auto-commit
 * while the network callback was still running. Never store identity material.
 */
export function withBootstrapLock<T>(
  work: (signal: AbortSignal) => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const controller = new AbortController()
    let db: IDBDatabase | undefined
    let transaction: IDBTransaction | undefined
    let finished = false
    let workSettled = false
    let value: T
    const timer = setTimeout(
      () =>
        fail(
          new DOMException("Session setup timed out; retry", "TimeoutError"),
        ),
      boundMs,
    )
    const cleanup = () => {
      clearTimeout(timer)
      signal?.removeEventListener("abort", cancel)
      window.removeEventListener("pagehide", closeTab)
      db?.close()
    }
    const fail = (error: unknown) => {
      if (finished) return
      finished = true
      controller.abort(error)
      try {
        transaction?.abort()
      } catch {
        /* Already aborted or complete. */
      }
      cleanup()
      reject(error)
    }
    const cancel = () =>
      fail(signal?.reason ?? new DOMException("Aborted", "AbortError"))
    const closeTab = () => fail(new DOMException("Tab closed", "AbortError"))
    if (signal?.aborted) {
      cancel()
      return
    }
    signal?.addEventListener("abort", cancel, { once: true })
    window.addEventListener("pagehide", closeTab, { once: true })

    try {
      const open = window.indexedDB.open(databaseName, 1)
      open.onupgradeneeded = () => {
        if (finished) {
          open.transaction?.abort()
          return
        }
        if (!open.result.objectStoreNames.contains(storeName))
          open.result.createObjectStore(storeName)
      }
      open.onerror = () => fail(storageUnavailable())
      open.onblocked = () => fail(storageUnavailable())
      open.onsuccess = () => {
        db = open.result
        if (finished) {
          db.close()
          return
        }
        db.onversionchange = () => fail(storageUnavailable())
        try {
          transaction = db.transaction(storeName, "readwrite")
          transaction.onabort = () => fail(storageUnavailable())
          transaction.onerror = () => fail(storageUnavailable())
          transaction.oncomplete = () => {
            if (finished) return
            if (!workSettled) {
              fail(storageUnavailable())
              return
            }
            finished = true
            cleanup()
            resolve(value)
          }
          const store = transaction.objectStore(storeName)
          const keepAlive = () => {
            if (finished || workSettled) return
            const request = store.get("bootstrap")
            request.onsuccess = keepAlive
            request.onerror = () => fail(storageUnavailable())
          }
          const acquired = store.put(1, "bootstrap")
          acquired.onerror = () => fail(storageUnavailable())
          acquired.onsuccess = () => {
            if (finished) return
            keepAlive()
            // Only this request's completion proves the writer was acquired.
            Promise.resolve()
              .then(() => work(controller.signal))
              .then((result) => {
                value = result
                workSettled = true
              }, fail)
          }
        } catch {
          fail(storageUnavailable())
        }
      }
    } catch {
      fail(storageUnavailable())
    }
  })
}
