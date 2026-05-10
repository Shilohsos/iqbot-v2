/**
 * iq-trader: V4 Hybrid trade executor.
 * Wraps @quadcode-tech/client-sdk-js in an Express HTTP server so the Python
 * bot can delegate trade placement and result-waiting to the official SDK.
 *
 * POST /trade   — place a binary/turbo option and wait for the result
 * POST /balance — fetch real + demo balances
 * GET  /health  — liveness probe
 */
import express from 'express';
import {
    ClientSdk,
    SsidAuthMethod,
    TurboOptionsDirection,
    BinaryOptionsDirection,
    BalanceType,
} from '@quadcode-tech/client-sdk-js';

const app = express();
app.use(express.json());

const WS_URL = process.env.IQ_WS_URL || 'wss://iqoption.com/echo/websocket';
const PORT   = parseInt(process.env.PORT || '3001', 10);

// Per-SSID SDK connection pool  { ssid -> { sdk, lastUsed } }
const pool = new Map();

async function getSdk(ssid, platformId) {
    const entry = pool.get(ssid);
    if (entry) {
        entry.lastUsed = Date.now();
        return entry.sdk;
    }
    console.log(`[iq-trader] Connecting SDK for platformId=${platformId}`);
    const sdk = await ClientSdk.create(
        WS_URL,
        platformId,
        new SsidAuthMethod(ssid),
        { host: 'https://iqoption.com' },
    );
    pool.set(ssid, { sdk, lastUsed: Date.now() });
    return sdk;
}

// Evict connections idle for > 30 min
setInterval(() => {
    const cutoff = Date.now() - 30 * 60 * 1000;
    for (const [key, entry] of pool.entries()) {
        if (entry.lastUsed < cutoff) {
            console.log('[iq-trader] Evicting idle connection');
            pool.delete(key);
        }
    }
}, 5 * 60 * 1000);

function pickDirection(dir, isTurbo) {
    if (isTurbo) {
        return dir === 'call' ? TurboOptionsDirection.Call : TurboOptionsDirection.Put;
    }
    return dir === 'call' ? BinaryOptionsDirection.Call : BinaryOptionsDirection.Put;
}

// Match pair name regardless of 'front.' prefix convention
function findActive(actives, pair) {
    const bare = pair.replace(/^front\./, '');
    return actives.find(a => {
        const t = (a.ticker || '').replace(/^front\./, '');
        const n = (a.name  || '').replace(/^front\./, '');
        return t === bare || n === bare || a.ticker === pair || a.name === pair;
    });
}

// Wait for a specific position to close, resolving with WIN/LOSS/TIE or TIMEOUT.
function waitForResult(positions, tradeId, timeoutMs) {
    return new Promise((resolve) => {
        let resolved = false;

        const timer = setTimeout(() => {
            if (!resolved) {
                resolved = true;
                resolve({ status: 'TIMEOUT', tradeId });
            }
        }, timeoutMs);

        positions.subscribeOnUpdatePosition((pos) => {
            if (resolved) return;
            // Match by externalId (set by IQ Option) or internal id
            if (pos.externalId !== tradeId && pos.id !== tradeId) return;

            // Closed = closedAt set, or explicit closed status
            const isClosed = pos.closedAt != null || pos.status === 'closed';
            if (!isClosed) return;

            resolved = true;
            clearTimeout(timer);

            const pnl = pos.pnlNet ?? 0;
            resolve({
                status: 'CLOSED',
                tradeId,
                result: pnl > 0 ? 'WIN' : (pnl < 0 ? 'LOSS' : 'TIE'),
                pnl,
            });
        });
    });
}

// ─── POST /trade ──────────────────────────────────────────────────────────────
app.post('/trade', async (req, res) => {
    const {
        ssid, platformId = 9,
        pair, direction, amount, durationSeconds, balanceType = 'PRACTICE',
    } = req.body;

    if (!ssid || !pair || !direction || amount == null || !durationSeconds) {
        return res.status(400).json({ status: 'ERROR', error: 'Missing required fields' });
    }

    let sdk;
    try {
        sdk = await getSdk(ssid, platformId);
    } catch (err) {
        pool.delete(ssid);
        console.error(`[iq-trader] SDK connect error: ${err.message}`);
        return res.status(502).json({ status: 'ERROR', error: `SDK connect failed: ${err.message}` });
    }

    try {
        // Balances
        const balancesModule = await sdk.balances();
        const targetType = balanceType === 'REAL' ? BalanceType.Real : BalanceType.Demo;
        const balance = balancesModule.getBalances().find(b => b.type === targetType);
        if (!balance) {
            return res.status(400).json({ status: 'ERROR', error: `No ${balanceType} balance found` });
        }

        // Subscribe to positions BEFORE buying so we don't miss the close event
        const positions = await sdk.positions();

        let bought;
        const isTurbo = durationSeconds <= 300;

        if (isTurbo) {
            const turboOptions = await sdk.turboOptions();
            const now = new Date();
            const actives = turboOptions.getActives().filter(a => a.canBeBoughtAt(now));
            const active = findActive(actives, pair);
            if (!active) {
                return res.status(400).json({ status: 'ERROR', error: `Asset ${pair} not available for turbo` });
            }
            const instruments = await active.instruments();
            const available = instruments.getAvailableForBuyAt(now);
            // Prefer exact duration match; fall back to nearest longer duration
            const instrument = available.find(i => i.durationSeconds === durationSeconds)
                ?? available.find(i => i.durationSeconds > durationSeconds)
                ?? available[0];
            if (!instrument) {
                return res.status(400).json({ status: 'ERROR', error: `No instrument for ${pair}@${durationSeconds}s` });
            }
            bought = await turboOptions.buy(instrument, pickDirection(direction, true), amount, balance);
        } else {
            const binaryOptions = await sdk.binaryOptions();
            const now = new Date();
            const actives = binaryOptions.getActives().filter(a => a.canBeBoughtAt(now));
            const active = findActive(actives, pair);
            if (!active) {
                return res.status(400).json({ status: 'ERROR', error: `Asset ${pair} not available for binary` });
            }
            const instruments = await active.instruments();
            const available = instruments.getAvailableForBuyAt(now);
            const instrument = available.find(i => i.durationSeconds === durationSeconds)
                ?? available.find(i => i.durationSeconds > durationSeconds)
                ?? available[0];
            if (!instrument) {
                return res.status(400).json({ status: 'ERROR', error: `No instrument for ${pair}@${durationSeconds}s` });
            }
            bought = await binaryOptions.buy(instrument, pickDirection(direction, false), amount, balance);
        }

        const tradeId = bought.id ?? bought.externalId;
        console.log(`[iq-trader] Placed id=${tradeId} pair=${pair} dir=${direction} amount=${amount}`);

        // Wait for result (trade duration + 90s grace period)
        const result = await waitForResult(positions, tradeId, (durationSeconds + 90) * 1000);
        console.log(`[iq-trader] Result: ${JSON.stringify(result)}`);

        return res.json({ status: 'OPENED', tradeId, ...result });

    } catch (err) {
        console.error(`[iq-trader] Trade error: ${err.message}`);
        // Evict if connection-level error so next request triggers a fresh connect
        if (/connect|websocket|socket|auth/i.test(err.message)) {
            pool.delete(ssid);
        }
        return res.status(500).json({ status: 'ERROR', error: err.message });
    }
});

// ─── POST /balance ─────────────────────────────────────────────────────────────
app.post('/balance', async (req, res) => {
    const { ssid, platformId = 9 } = req.body;
    if (!ssid) return res.status(400).json({ error: 'Missing ssid' });

    let sdk;
    try {
        sdk = await getSdk(ssid, platformId);
    } catch (err) {
        pool.delete(ssid);
        return res.status(502).json({ error: `SDK connect failed: ${err.message}` });
    }

    try {
        const balancesModule = await sdk.balances();
        const bals = balancesModule.getBalances();
        const real = bals.find(b => b.type === BalanceType.Real);
        const demo = bals.find(b => b.type === BalanceType.Demo);
        return res.json({
            real: real ? { amount: real.amount, currency: real.currency } : null,
            demo: demo ? { amount: demo.amount, currency: demo.currency } : null,
        });
    } catch (err) {
        pool.delete(ssid);
        return res.status(500).json({ error: err.message });
    }
});

// ─── GET /health ──────────────────────────────────────────────────────────────
app.get('/health', (_req, res) => {
    res.json({ ok: true, connections: pool.size });
});

app.listen(PORT, () => console.log(`[iq-trader] Listening on :${PORT}`));
