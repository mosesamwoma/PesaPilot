const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const cron = require('node-cron');
const fs = require('fs');
const os = require('os');
const path = require('path');
require('dotenv').config();

const MAIN_NUMBER = process.env.WHATSAPP_MAIN_NUMBER;
const WHATSAPP_LID = process.env.WHATSAPP_LID;
const WHATSAPP_PIN = process.env.WHATSAPP_PIN;
const API_URL = process.env.API_URL || 'http://127.0.0.1:8000';
const API_TOKEN = (process.env.API_TOKEN || '').trim();
const AUTH_HEADERS = { Authorization: `Bearer ${API_TOKEN}` };
const AUTH_PATH = process.env.WWEBJS_AUTH_PATH || './.wwebjs_auth';

const IS_WINDOWS = process.platform === 'win32';
const IS_MAC = process.platform === 'darwin';
const HOME_DIR = os.homedir();
const WIN_ROOTS = [process.env.PROGRAMFILES, process.env['PROGRAMFILES(X86)'], process.env.LOCALAPPDATA].filter(Boolean);

const BROWSER_FAMILIES = [
    {
        id: 'chromium',
        names: ['chromium', 'chromium-browser', 'ungoogled-chromium'],
        linux: ['/usr/lib/chromium/chromium', '/usr/lib/chromium-browser/chromium-browser'],
        mac: ['/Applications/Chromium.app/Contents/MacOS/Chromium'],
        win: ['Chromium\\Application\\chrome.exe']
    },
    {
        id: 'chrome',
        names: ['google-chrome-stable', 'google-chrome', 'google-chrome-beta', 'google-chrome-unstable', 'chrome'],
        linux: ['/opt/google/chrome/chrome', '/opt/google/chrome/google-chrome'],
        mac: ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'],
        win: ['Google\\Chrome\\Application\\chrome.exe']
    },
    {
        id: 'brave',
        names: ['brave-browser', 'brave-browser-stable', 'brave', 'brave-origin'],
        linux: ['/opt/brave.com/brave/brave', '/opt/brave-bin/brave', '/opt/brave-origin-bin/brave', '/usr/lib/brave-bin/brave'],
        mac: ['/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'],
        win: ['BraveSoftware\\Brave-Browser\\Application\\brave.exe']
    },
    {
        id: 'helium',
        names: ['helium', 'helium-browser'],
        linux: ['/opt/helium/helium', '/opt/helium-browser/helium', '/opt/helium-bin/helium', '/opt/helium-browser-bin/helium'],
        mac: ['/Applications/Helium.app/Contents/MacOS/Helium'],
        win: ['Helium\\Application\\helium.exe', 'Programs\\Helium\\helium.exe']
    },
    {
        id: 'edge',
        names: ['microsoft-edge-stable', 'microsoft-edge', 'msedge'],
        linux: ['/opt/microsoft/msedge/msedge'],
        mac: ['/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'],
        win: ['Microsoft\\Edge\\Application\\msedge.exe']
    },
    {
        id: 'vivaldi',
        names: ['vivaldi-stable', 'vivaldi'],
        linux: ['/opt/vivaldi/vivaldi'],
        mac: ['/Applications/Vivaldi.app/Contents/MacOS/Vivaldi'],
        win: ['Vivaldi\\Application\\vivaldi.exe']
    },
    {
        id: 'thorium',
        names: ['thorium-browser', 'thorium'],
        linux: ['/opt/chromium.org/thorium/thorium-browser', '/opt/thorium-browser/thorium-browser'],
        mac: ['/Applications/Thorium.app/Contents/MacOS/Thorium'],
        win: ['Thorium\\Application\\thorium.exe']
    },
    {
        id: 'opera',
        names: ['opera'],
        linux: ['/usr/lib/x86_64-linux-gnu/opera/opera', '/usr/lib64/opera/opera'],
        mac: ['/Applications/Opera.app/Contents/MacOS/Opera'],
        win: ['Opera\\opera.exe', 'Programs\\Opera\\opera.exe']
    }
];

function isExecutableFile(candidate) {
    try {
        if (!candidate || !path.isAbsolute(candidate)) return false;
        if (!fs.statSync(candidate).isFile()) return false;
        if (!IS_WINDOWS) fs.accessSync(candidate, fs.constants.X_OK);
        return true;
    } catch (e) {
        return false;
    }
}

function listDir(dir) {
    try {
        return fs.readdirSync(dir);
    } catch (e) {
        return [];
    }
}

function fromPath(name) {
    const dirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
    const fileNames = IS_WINDOWS ? [`${name}.exe`, name] : [name];
    const found = [];
    for (const dir of dirs) {
        for (const fileName of fileNames) {
            const full = path.join(dir, fileName);
            if (isExecutableFile(full)) found.push(full);
        }
    }
    return found;
}

function fromOptScan(names) {
    const found = [];
    for (const entry of listDir('/opt')) {
        for (const name of names) {
            const direct = path.join('/opt', entry, name);
            if (isExecutableFile(direct)) found.push(direct);
            for (const sub of listDir(path.join('/opt', entry))) {
                const nested = path.join('/opt', entry, sub, name);
                if (isExecutableFile(nested)) found.push(nested);
            }
        }
    }
    return found;
}

function fromPuppeteerCache() {
    const found = [];
    const roots = [process.env.PUPPETEER_CACHE_DIR, path.join(HOME_DIR, '.cache', 'puppeteer')].filter(Boolean);
    for (const root of roots) {
        for (const version of listDir(path.join(root, 'chrome'))) {
            const versionDir = path.join(root, 'chrome', version);
            for (const platformDir of listDir(versionDir)) {
                const linux = path.join(versionDir, platformDir, 'chrome');
                const win = path.join(versionDir, platformDir, 'chrome.exe');
                const mac = path.join(versionDir, platformDir, 'Google Chrome for Testing.app', 'Contents', 'MacOS', 'Google Chrome for Testing');
                for (const candidate of [linux, win, mac]) {
                    if (isExecutableFile(candidate)) found.push(candidate);
                }
            }
        }
    }
    return found;
}

function candidatesForFamily(family) {
    const found = [];
    for (const name of family.names) found.push(...fromPath(name));
    if (IS_MAC) {
        for (const candidate of family.mac) {
            found.push(candidate, path.join(HOME_DIR, candidate));
        }
    } else if (IS_WINDOWS) {
        for (const root of WIN_ROOTS) {
            for (const relative of family.win) found.push(path.join(root, relative));
        }
    } else {
        for (const name of family.names) {
            found.push(path.join('/usr/bin', name), path.join('/usr/local/bin', name), path.join(HOME_DIR, '.local', 'bin', name));
        }
        found.push(...family.linux);
        found.push(...fromOptScan(family.names));
    }
    return found.filter(isExecutableFile);
}

function orderedFamilies() {
    const preferred = (process.env.BROWSER_PREFERENCE || '')
        .split(',')
        .map((value) => value.trim().toLowerCase())
        .filter(Boolean);
    const known = new Set(BROWSER_FAMILIES.map((family) => family.id));
    for (const value of preferred) {
        if (!known.has(value)) {
            console.warn(`BROWSER_PREFERENCE: unknown browser "${value}" ignored (known: ${[...known].join(', ')})`);
        }
    }
    const first = preferred.map((value) => BROWSER_FAMILIES.find((family) => family.id === value)).filter(Boolean);
    const rest = BROWSER_FAMILIES.filter((family) => !first.includes(family));
    return [...first, ...rest];
}

function findBrowserExecutable() {
    for (const envName of ['PUPPETEER_EXECUTABLE_PATH', 'CHROME_PATH']) {
        const configured = (process.env[envName] || '').trim();
        if (!configured) continue;
        if (isExecutableFile(configured)) {
            return { path: configured, label: `${envName}` };
        }
        console.warn(`WARNING: ${envName}="${configured}" is not an executable file; trying auto-detection instead.`);
    }

    for (const family of orderedFamilies()) {
        const [first] = candidatesForFamily(family);
        if (first) return { path: first, label: family.id };
    }

    const [cached] = fromPuppeteerCache();
    if (cached) return { path: cached, label: 'puppeteer cache' };

    return null;
}

const BROWSER = findBrowserExecutable();

if (!BROWSER) {
    console.error('\nERROR: No Chromium-based browser was found.');
    console.error(`Looked for: ${BROWSER_FAMILIES.map((family) => family.id).join(', ')} (PATH, standard install folders, /opt, Puppeteer cache).`);
    console.error('Install one of them, or set PUPPETEER_EXECUTABLE_PATH to the full path of its executable.');
    console.error('Example: PUPPETEER_EXECUTABLE_PATH=/usr/bin/brave-browser\n');
    process.exit(1);
}

const CHROME_PATH = BROWSER.path;

if (!MAIN_NUMBER || !WHATSAPP_PIN || !API_TOKEN) {
    console.error('\nERROR: Missing required .env variables:');
    if (!MAIN_NUMBER) console.error('  - WHATSAPP_MAIN_NUMBER');
    if (!WHATSAPP_PIN) console.error('  - WHATSAPP_PIN');
    if (!API_TOKEN) console.error('  - API_TOKEN');
    process.exit(1);
}

(function checkApiUrl(rawUrl) {
    let parsed;
    try {
        parsed = new URL(rawUrl);
    } catch (e) {
        console.error('\nERROR: API_URL is not a valid URL');
        process.exit(1);
    }
    const isLoopback = ['127.0.0.1', 'localhost', '[::1]', '::1'].includes(parsed.hostname);
    if (parsed.protocol !== 'https:' && !isLoopback) {
        console.warn(`\nWARNING: API_URL (${parsed.protocol}//${parsed.host}) is not HTTPS and not localhost. The API token would travel unencrypted. Use https:// or keep the API on the same machine.\n`);
    }
})(API_URL);

function digitsOnly(value) {
    return (value || '').replace(/@.*$/, '').replace(/:\d+$/, '').replace(/\D/g, '');
}

function safeLog(text) {
    return (text || '').replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029\u200b-\u200f\u202a-\u202e\u2066-\u2069]+/g, ' ');
}

function toWhatsAppFormat(text) {
    return (text || '')
        .replace(/^#{1,6}\s+(.+)$/gm, (_m, title) => `**${title.replace(/\*\*/g, '')}**`)
        .replace(/\*\*(.+?)\*\*/g, '*$1*');
}

console.log('\n═══════════════════════════════════════════════════════');
console.log('PesaPilot WhatsApp Bot v1.3');
console.log('═══════════════════════════════════════════════════════');
console.log(`Phone Number : configured`);
console.log(`LID          : ${WHATSAPP_LID ? 'configured' : 'not set (resolved automatically)'}`);
console.log(`PIN          : configured`);
console.log(`API URL      : ${API_URL}`);
console.log(`Browser      : ${BROWSER.label} (${CHROME_PATH})`);
console.log('═══════════════════════════════════════════════════════\n');

const LOCK_NAMES = new Set(['SingletonLock', 'SingletonSocket', 'SingletonCookie', 'SingletonTab']);

function cleanupChromeLocks(dir) {
    let removed = 0;
    let entries;
    try {
        entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (e) {
        return removed;
    }
    for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (LOCK_NAMES.has(entry.name) || entry.name.endsWith('.lock')) {
            try {
                fs.rmSync(fullPath, { force: true });
                removed++;
            } catch (e) {}
        } else if (entry.isDirectory()) {
            removed += cleanupChromeLocks(fullPath);
        }
    }
    return removed;
}

try {
    fs.mkdirSync(AUTH_PATH, { recursive: true });
    const removed = cleanupChromeLocks(AUTH_PATH);
    console.log(`Pre-launch lock check: removed ${removed} stale lock file(s)\n`);
} catch (e) {
    console.warn(`Pre-launch lock cleanup skipped: ${e.message}\n`);
}

const client = new Client({
    authStrategy: new LocalAuth({
        dataPath: AUTH_PATH,
        clientId: 'pesapilot-session'
    }),
    puppeteer: {
        headless: true,
        executablePath: CHROME_PATH,
        protocolTimeout: 180000,
        timeout: 180000,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--disable-accelerated-video-decode',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-breakpad',
            '--disable-client-side-phishing-detection',
            '--disable-crash-reporter',
            '--disable-default-apps',
            '--disable-extensions',
            '--disable-features=IsolateOrigins,site-per-process',
            '--disable-gpu',
            '--disable-hang-monitor',
            '--disable-infobars',
            '--disable-ipc-flooding-protection',
            '--disable-notifications',
            '--disable-popup-blocking',
            '--disable-prompt-on-repost',
            '--disable-renderer-backgrounding',
            '--disable-software-rasterizer',
            '--disable-sync',
            '--disable-translate',
            '--disk-cache-size=0',
            '--enable-features=NetworkService,NetworkServiceInProcess',
            '--hide-scrollbars',
            '--mute-audio',
            '--no-cache',
            '--no-default-browser-check',
            '--no-first-run',
            '--password-store=basic',
            '--use-mock-keychain',
            '--window-size=1280,720'
        ]
    }
});

const STARTUP_TIMEOUT_MS = 120 * 1000;
let startupResolved = false;
const startupWatchdog = setTimeout(() => {
    if (!startupResolved) {
        console.error(`\nNo QR code or ready event after ${STARTUP_TIMEOUT_MS / 1000}s — Chrome likely failed to launch.`);
        console.error(' Exiting so the container restarts and re-runs lock cleanup.\n');
        process.exit(1);
    }
}, STARTUP_TIMEOUT_MS);
startupWatchdog.unref();
let isReady = false;

client.on('qr', (qr) => {
    startupResolved = true;
    console.log('\n╔════════════════════════════════════════════════════════╗');
    console.log('║        SCAN QR CODE WITH YOUR SPARE AIRTEL PHONE       ║');
    console.log('║  Settings → Linked Devices → Link a Device             ║');
    console.log('╚════════════════════════════════════════════════════════╝\n');

    try {
        qrcode.generate(qr, { small: true, scale: 1 });
    } catch (e) {
        console.warn(`QR rendering error: ${e.message}`);
    }

    if ((process.env.WHATSAPP_QR_LINK || 'false').toLowerCase() === 'true') {
        const qrServerUrl = `https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=${encodeURIComponent(qr)}`;
        console.warn('\nWARNING: WHATSAPP_QR_LINK=true sends your WhatsApp login QR to a third-party service (api.qrserver.com). Anyone with this link can link a device to your WhatsApp. Set WHATSAPP_QR_LINK=false.');
        console.log(`QR fallback link:\n${qrServerUrl}\n`);
    }

    console.log('⏳ Waiting for scan (scan within 2 minutes)...\n');
});

client.on('ready', () => {
    startupResolved = true;
    isReady = true;
    console.log('\n╔═══════════════════════════════════════════════════════╗');
    console.log('║                 BOT IS ONLINE                         ║');
    console.log('╚═══════════════════════════════════════════════════════╝');
    console.log(`Bot WhatsApp ID : ${client.info.wid._serialized}`);
    console.log(`API             : ${API_URL}`);
    console.log('\nCommands: Summary, Weekly summary, Monthly summary, Help, Bar chart, Pie chart, Trend');
    console.log(`Manual entry: PIN-SMS_CONTENT\n`);
});

client.on('loading_screen', (percent, message) => {
    console.log(`⏳ Loading WhatsApp Web: ${percent}% — ${message}`);
});

client.on('auth_failure', (msg) => {
    console.error(`\nAuthentication failure: ${msg}`);
    console.error(' The saved session is likely corrupted. Exiting so the');
    console.error(' container restarts; if this repeats, delete the');
    console.error(' .wwebjs_auth volume once and re-scan the QR code.\n');
    process.exit(1);
});

client.on('change_state', (state) => {
    console.log(`Connection state: ${state}`);
});

async function resolveSenderIds(message) {
    const ids = new Set();
    const add = (value) => {
        const digits = digitsOnly(value);
        if (digits) ids.add(digits);
    };

    add(message.from);

    if (message.from.endsWith('@lid')) {
        try {
            const resolved = await client.getContactLidAndPhone([message.from]);
            for (const entry of resolved || []) {
                add(entry.pn);
                add(entry.lid);
            }
        } catch (e) {}
    }

    try {
        const contact = await message.getContact();
        add(contact.number);
        add(contact.id && contact.id.user);
    } catch (e) {}

    return [...ids];
}

client.on('message', async (message) => {
    let authorizedSender = false;
    try {
        if (!message.from || message.from.endsWith('@g.us') || message.from.endsWith('@broadcast')) return;

        const userMessage = (message.body || '').trim();
        if (!userMessage) return;
        const mainNumeric = digitsOnly(MAIN_NUMBER);
        const lidNumeric = digitsOnly(WHATSAPP_LID);

        const senderIds = await resolveSenderIds(message);
        const isAuthorized = senderIds.some(
            (id) => (mainNumeric !== '' && id === mainNumeric) || (lidNumeric !== '' && id === lidNumeric)
        );

        console.log(`\nFrom: ${senderIds.join(' / ')}`);
        const loggable = userMessage.startsWith(WHATSAPP_PIN + '-') ? '[manual SMS entry - content hidden]' : safeLog(userMessage);
        console.log(`Msg: "${loggable.substring(0, 50)}${loggable.length > 50 ? '...' : ''}"`);

        if (!isAuthorized) {
            console.log('Non-main sender — leaving for manual reply');
            return;
        }

        authorizedSender = true;
        console.log('Authorized');
        try { await message.react('⏳'); } catch (e) {}

        if (userMessage.startsWith(WHATSAPP_PIN + '-')) {
            console.log('Manual SMS entry');
            const smsContent = userMessage.substring(WHATSAPP_PIN.length + 1).trim();
            if (!smsContent) {
                await message.reply('❌ Format: PIN-SMS_CONTENT');
                return;
            }
            try {
                const response = await axios.post(`${API_URL}/parse-sms`, { sms_content: smsContent }, { timeout: 20000, headers: AUTH_HEADERS });
                if (response.data.success) {
                    await message.reply(toWhatsAppFormat(response.data.summary));
                    try { await message.react('✅'); } catch (e) {}
                } else {
                    await message.reply(response.data.summary || (response.data.error ? `❌ ${response.data.error}` : '❌ Could not parse SMS'));
                    try { await message.react('❌'); } catch (e) {}
                }
            } catch (error) {
                await message.reply('❌ Error processing SMS.');
                try { await message.react('❌'); } catch (e) {}
            }
            return;
        }

        try {
            const response = await axios.post(`${API_URL}/ask`, { question: userMessage }, { timeout: 30000, headers: AUTH_HEADERS });

            if (response.data.chart) {
                try {
                    const media = new MessageMedia('image/png', response.data.chart, 'chart.png');
                    const analysisText = toWhatsAppFormat(response.data.analysis || '');
                    const captionFits = analysisText.length <= 1000;
                    await client.sendMessage(message.from, media, { caption: captionFits ? (analysisText || '📊 Chart') : '📊 Chart' });
                    if (!captionFits) {
                        for (const chunk of splitMessage(analysisText.substring(0, 4000), 3000)) {
                            await message.reply(chunk);
                            await new Promise(r => setTimeout(r, 500));
                        }
                    }
                    try { await message.react('📊'); } catch (e) {}
                } catch (chartError) {
                    await message.reply(`${toWhatsAppFormat(response.data.analysis)}\n\n(Chart unavailable)`);
                    try { await message.react('✅'); } catch (e) {}
                }
                return;
            }

            let analysis = toWhatsAppFormat(response.data.analysis || 'No response');
            if (analysis.length > 4000) {
                analysis = analysis.substring(0, 4000) + '\n\n...(truncated)';
            }
            const chunks = splitMessage(analysis, 3000);
            for (let i = 0; i < chunks.length; i++) {
                await message.reply(chunks[i]);
                if (i < chunks.length - 1) await new Promise(r => setTimeout(r, 500));
            }
            try { await message.react('✅'); } catch (e) {}

        } catch (error) {
            console.error(`Error: ${error.message}`);
            await message.reply('❌ Error processing your request.');
            try { await message.react('❌'); } catch (e) {}
        }

    } catch (error) {
        console.error(`Fatal: ${error.message}`);
        if (authorizedSender) {
            try { await message.reply('❌ Something went wrong.'); } catch (e) {}
        }
    }
});

client.on('disconnected', (reason) => {
    isReady = false;
    console.log(`\nDisconnected: ${reason}`);
    if (shuttingDown) return;
    if (reason === 'LOGOUT') {
        console.error(' Session logged out. Waiting for a fresh QR code to re-link the bot.\n');
        return;
    }
    console.error(' Exiting so the process restarts and re-initialises the client.\n');
    process.exit(1);
});

const mainNumeric = digitsOnly(MAIN_NUMBER);
const DAILY_SUMMARY_CHAT_ID = `${mainNumeric}@c.us`;

cron.schedule('0 21 * * *', async () => {
    console.log('\n⏰ Running scheduled daily summary job (21:00 Africa/Nairobi)...');
    if (!isReady) {
        console.warn('Skipped: bot is not currently connected.\n');
        return;
    }
    try {
        const response = await axios.get(`${API_URL}/daily-summary`, { timeout: 20000, headers: AUTH_HEADERS });
        const summaryText = response?.data?.summary || '⚠️ Could not generate summary.';
        await client.sendMessage(DAILY_SUMMARY_CHAT_ID, toWhatsAppFormat(summaryText));
        console.log('Daily summary sent successfully\n');
    } catch (error) {
        console.error(`Daily summary cron error: ${error.message}\n`);
    }
}, { timezone: 'Africa/Nairobi' });

console.log('Daily summary scheduled for 9:00 PM Africa/Nairobi every day\n');

cron.schedule('0 */2 * * *', async () => {
    console.log('\n⏰ Running scheduled budget check job...');
    if (!isReady) {
        console.warn('Skipped: bot is not currently connected.\n');
        return;
    }
    try {
        const response = await axios.get(`${API_URL}/budget-check`, { timeout: 20000, headers: AUTH_HEADERS });
        const alerts = response?.data?.alerts || [];

        if (alerts.length === 0) {
            console.log('Budget check: nothing new to report.\n');
            return;
        }

        let delivered = 0;
        for (const alert of alerts) {
            try {
                const icon = alert.alert_level === 'over' ? '🚨' : '⚠️';
                await client.sendMessage(DAILY_SUMMARY_CHAT_ID, `${icon} ${toWhatsAppFormat(alert.message)}`);
            } catch (sendError) {
                console.error(`Budget alert for ${alert.category} not delivered, will retry next check: ${sendError.message}`);
                continue;
            }
            delivered++;
            try {
                await axios.post(`${API_URL}/budget-alerts/ack`, {
                    budget_id: alert.budget_id,
                    period_start: alert.period_start,
                    alert_level: alert.alert_level,
                    amount_spent: alert.amount_spent
                }, { timeout: 20000, headers: AUTH_HEADERS });
            } catch (ackError) {
                console.error(`Budget alert for ${alert.category} was sent but could not be acknowledged (may repeat): ${ackError.message}`);
            }
            await new Promise(resolve => setTimeout(resolve, 500));
        }
        console.log(`Sent ${delivered}/${alerts.length} budget alert(s)\n`);
    } catch (error) {
        console.error(`Budget check cron error: ${error.message}\n`);
    }
}, { timezone: 'Africa/Nairobi' });

console.log('Budget check scheduled every 2 hours (Africa/Nairobi)\n');

const DEFAULT_WEEKLY_SUMMARY_CRON = '0 8 * * 1';
const DEFAULT_MONTHLY_SUMMARY_CRON = '30 8 1 * *';
const SUMMARY_MAX_ATTEMPTS = 3;
const SUMMARY_RETRY_DELAY_MS = 10 * 60 * 1000;

function resolveCronExpression(envName, fallback) {
    const raw = (process.env[envName] || '').trim();
    if (!raw) return fallback;
    if (raw.toLowerCase() === 'off') return null;
    if (cron.validate(raw)) return raw;
    console.warn(`${envName} is not a valid cron expression ("${raw}"), using default "${fallback}"`);
    return fallback;
}

async function sendPeriodSummary(label, endpoint, attempt = 1) {
    try {
        if (!isReady) {
            throw new Error('bot is not currently connected');
        }
        const response = await axios.get(`${API_URL}${endpoint}`, { timeout: 30000, headers: AUTH_HEADERS });
        const text = ((response && response.data && response.data.summary) || '').trim();
        if (!text) {
            throw new Error('API returned an empty summary');
        }
        await client.sendMessage(DAILY_SUMMARY_CHAT_ID, toWhatsAppFormat(text));
        console.log(`${label} summary sent successfully\n`);
    } catch (error) {
        console.error(`${label} summary attempt ${attempt}/${SUMMARY_MAX_ATTEMPTS} failed: ${error.message}\n`);
        if (attempt < SUMMARY_MAX_ATTEMPTS) {
            console.log(`${label} summary will retry in ${SUMMARY_RETRY_DELAY_MS / 60000} minutes\n`);
            setTimeout(() => {
                sendPeriodSummary(label, endpoint, attempt + 1);
            }, SUMMARY_RETRY_DELAY_MS);
        } else {
            console.error(`${label} summary gave up after ${SUMMARY_MAX_ATTEMPTS} attempts\n`);
        }
    }
}

const PERIOD_SUMMARY_JOBS = [
    { label: 'Weekly', endpoint: '/weekly-summary', envName: 'WEEKLY_SUMMARY_CRON', fallback: DEFAULT_WEEKLY_SUMMARY_CRON },
    { label: 'Monthly', endpoint: '/monthly-summary', envName: 'MONTHLY_SUMMARY_CRON', fallback: DEFAULT_MONTHLY_SUMMARY_CRON },
];

for (const job of PERIOD_SUMMARY_JOBS) {
    const expression = resolveCronExpression(job.envName, job.fallback);
    if (expression === null) {
        console.log(`${job.label} summary disabled (${job.envName}=off)\n`);
        continue;
    }
    cron.schedule(expression, () => {
        console.log(`\n⏰ Running scheduled ${job.label.toLowerCase()} summary job...`);
        sendPeriodSummary(job.label, job.endpoint);
    }, { timezone: 'Africa/Nairobi' });
    console.log(`${job.label} summary scheduled with "${expression}" (Africa/Nairobi)\n`);
}

function splitMessage(text, maxLength) {
    if (text.length <= maxLength) return [text];
    const chunks = [];
    let currentChunk = '';
    const sentences = text.split(/(?<=[.!?])\s+/);
    for (const sentence of sentences) {
        if ((currentChunk + sentence).length > maxLength) {
            if (currentChunk) chunks.push(currentChunk.trim());
            currentChunk = sentence;
        } else {
            currentChunk += (currentChunk ? ' ' : '') + sentence;
        }
    }
    if (currentChunk) chunks.push(currentChunk.trim());
    return chunks;
}

let shuttingDown = false;
async function shutdown(signal, exitCode = 0) {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(`\nReceived ${signal}, shutting down...`);

    const forceExit = setTimeout(() => {
        console.warn('client.destroy() did not finish in time — forcing exit.');
        process.exit(exitCode);
    }, 10000);
    forceExit.unref();

    try {
        await client.destroy();
    } catch (e) {
        console.warn(`Error during client.destroy(): ${e.message}`);
    }
    clearTimeout(forceExit);
    process.exit(exitCode);
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

process.on('unhandledRejection', (reason) => {
    console.error('Unhandled promise rejection:', reason);
});

process.on('uncaughtException', (err) => {
    console.error('Uncaught exception:', err);
    shutdown('uncaughtException', 1);
});

console.log('Initializing WhatsApp client...\n');

let retryCount = 0;
const maxRetries = 3;

function startClient() {
    client.initialize().catch(async (err) => {
        console.error(`client.initialize() failed: ${err.message}`);

        try {
            await client.destroy();
        } catch (e) {}

        if (retryCount < maxRetries) {
            retryCount++;
            console.log(`Retry ${retryCount}/${maxRetries} in 5 seconds...`);
            setTimeout(() => {
                console.log('Re-initializing WhatsApp client...');
                startClient();
            }, 5000);
        } else {
            console.error(`Failed after ${maxRetries} retries. Exiting.`);
            process.exit(1);
        }
    });
}

startClient();