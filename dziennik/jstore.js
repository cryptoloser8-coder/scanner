// dziennik/jstore.js - zapis Dziennika na koncie (Firebase), poprawka 134.
// Przeniesione z apki portfela (tam: jeden plik journal.json w Cloudflare KV, tylko dla wlasciciela).
//
// Kazda osoba ma wlasny dziennik. Czesci leza osobno w Firestore, w tej samej kolekcji co rysunki:
//   users/{uid}/scopes/dziennik:<czesc>  { j: tekst JSON, n, page: 'dziennik', at }
// (reguly scopes juz pozwalaja wlascicielowi czytac i pisac - bez zmiany regul).
//   notes    - notatki do wydarzen (takze rynkowych); bez zrzutow ekranu
//   own      - wlasne wydarzenia
//   scene    - legendy i nagrobki
//   stickies - karteczki
//   seen     - kopie wydarzen rynkowych (zostaja, nawet gdy znikna z config.yaml)
//   cycles   - cykle wpisane recznie (start, koniec, kwoty)
// Bez logowania (albo z zablokowanym kontem): tylko przegladanie, nic sie nie zapisuje (J.ro = true).

const KEYS = ['notes', 'own', 'scene', 'stickies', 'seen', 'cycles'];
const MAX = 900000;                                   // Firestore: dokument do 1 MiB
export const J = { doc: null, ro: true, uid: null, loaded: false };

let onStatus = () => {};
export function setStoreHooks(h) { if (h.onStatus) onStatus = h.onStatus; }

function norm(d) {
    d = d && typeof d === 'object' && !Array.isArray(d) ? d : {};
    const obj = v => v && typeof v === 'object' && !Array.isArray(v) ? v : {};
    return {
        notes: obj(d.notes),
        own: Array.isArray(d.own) ? d.own : [],
        scene: d.scene && typeof d.scene === 'object' ? d.scene : null,
        stickies: Array.isArray(d.stickies) ? d.stickies.filter(q => q && typeof q.t === 'string').slice(0, 8) : [],
        seen: obj(d.seen),
        cycles: Array.isArray(d.cycles) ? d.cycles.filter(c => c && c.id && c.startAt).slice(0, 40) : []
    };
}

const A = () => window.CLAuth;
const live = () => { const a = A(); return !!(a && a.user && a.allowed && a.F); };
const cdoc = k => { const a = A(); return a.F.doc(a.db, 'users', a.user.uid, 'scopes', encodeURIComponent('dziennik:' + k)); };

// czeka, az app.js ustali, czy ktos jest zalogowany (przy pierwszej wizycie od razu: nikt)
function authReady() {
    return new Promise(res => {
        const a = A();
        if (!a) return res(null);
        let done = false;
        const fin = () => { if (!done && a.ready) { done = true; res(a); } };
        a.on(fin); fin();
        const t0 = Date.now(), iv = setInterval(() => { fin(); if (done || Date.now() - t0 > 12000) { clearInterval(iv); if (!done) { done = true; res(a); } } }, 150);
    });
}

export async function loadJournal() {
    const a = await authReady();
    J.doc = norm({});
    if (live()) {
        J.uid = a.user.uid;
        const parts = await Promise.all(KEYS.map(k => a.F.getDoc(cdoc(k)).then(s => {
            if (!s.exists()) return [k, undefined];
            try { return [k, JSON.parse(s.data().j)]; } catch (e) { return [k, undefined]; }
        })));
        const raw = {}; parts.forEach(([k, v]) => { if (v !== undefined) raw[k] = v; });
        J.doc = norm(raw);
        J.ro = false;
    } else {
        J.uid = null; J.ro = true;
    }
    J.loaded = true;
    // logowanie albo wylogowanie na tej stronie: wczytaj dziennik od nowa (inna osoba = inny dziennik)
    if (a) a.on(() => {
        if (!a.ready) return;
        const uid = live() ? a.user.uid : null;
        if (uid !== J.uid) { flushJournal().finally(() => location.reload()); }
    });
    return J.doc;
}

// ---------------------------------------------------------------- zapis

const dirty = new Set();
let timer = null, busy = false;
function schedule(ms) { clearTimeout(timer); timer = setTimeout(() => { timer = null; flushJournal(); }, ms); }

export function saveJournal(key, delay = 1200) {
    if (!KEYS.includes(key) || J.ro) return;
    dirty.add(key);
    onStatus('pending');
    schedule(delay);
}

export async function flushJournal() {
    if (!J.loaded || J.ro || !dirty.size) return true;
    if (!live()) { onStatus('error', 'nie jesteś zalogowany'); return false; }
    if (busy) { schedule(600); return false; }
    busy = true;
    const keys = [...dirty];
    dirty.clear();
    try {
        const a = A();
        await Promise.all(keys.map(k => {
            const v = J.doc[k], j = JSON.stringify(v === undefined ? null : v);
            if (j.length > MAX) throw new Error('za dużo tekstu w jednej części dziennika (' + k + ') — skróć notatki');
            return a.F.setDoc(cdoc(k), { j, n: Array.isArray(v) ? v.length : Object.keys(v || {}).length, page: 'dziennik', at: a.F.serverTimestamp() });
        }));
        onStatus('saved');
        return true;
    } catch (e) {
        keys.forEach(k => dirty.add(k));
        onStatus('error', e && (e.code || e.message) || 'błąd');
        schedule(8000);
        return false;
    } finally {
        busy = false;
        if (dirty.size && !timer) schedule(1200);
    }
}

// zamkniecie karty z niezapisana zmiana: ostatnia proba
window.addEventListener('pagehide', () => { if (dirty.size) flushJournal(); });
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden' && dirty.size) flushJournal(); });
