interface ExportMessages {
    wrongSite: string;
    signedOut: string;
    failed: string;
}

// This function is deliberately self-contained: the user runs its text on RPLAY.
// No network requests, refresh tokens, browser-wide data or console credentials.
async function exportRplaySession(messages: ExportMessages) {
    if (location.protocol !== 'https:' || !['rplay.live', 'www.rplay.live'].includes(location.hostname)) {
        alert(messages.wrongSite);
        return;
    }
    let database: IDBDatabase | undefined;
    try {
        database = await new Promise<IDBDatabase>((resolve, reject) => {
            const request = indexedDB.open('rplay-account-session');
            request.onupgradeneeded = () => request.transaction?.abort();
            request.onerror = () => reject(new Error('storage'));
            request.onblocked = () => reject(new Error('storage'));
            request.onsuccess = () => resolve(request.result);
        });
        const record = await new Promise<{ session?: { token?: unknown; user?: { oid?: unknown; _id?: unknown }; loginType?: unknown } } | undefined>((resolve, reject) => {
            const transaction = database!.transaction('records', 'readonly');
            const request = transaction.objectStore('records').get('session');
            transaction.oncomplete = () => resolve(request.result);
            transaction.onerror = () => reject(new Error('storage'));
            transaction.onabort = () => reject(new Error('storage'));
        });
        const session = record?.session;
        const accessToken = session?.token;
        const requestorOid = session?.user?.oid || session?.user?._id;
        const loginType = session?.loginType;
        if (typeof accessToken !== 'string' || !/^[A-Za-z0-9._~+/=-]{16,8192}$/.test(accessToken)
            || typeof requestorOid !== 'string' || !/^[a-fA-F0-9]{24}$/.test(requestorOid)
            || typeof loginType !== 'string' || !/^[A-Za-z0-9_-]{1,32}$/.test(loginType)) {
            alert(messages.signedOut);
            return;
        }
        const file = new Blob([JSON.stringify({ accessToken, requestorOid, loginType }, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(file);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'rplay_session.json';
        document.body.append(link);
        try { link.click(); }
        finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
    } catch {
        alert(messages.failed);
    } finally {
        database?.close();
    }
}

export function makeRplaySessionExportScript(messages: ExportMessages): string {
    return `(${exportRplaySession.toString()})(${JSON.stringify(messages)});`;
}
