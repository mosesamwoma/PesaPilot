const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const cron = require('node-cron');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

const MAIN_NUMBER = process.env.WHATSAPP_MAIN_NUMBER;
const WHATSAPP_LID = process.env.WHATSAPP_LID;
const WHATSAPP_PIN = process.env.WHATSAPP_PIN;
const API_URL = process.env.API_URL || 'http://127.0.0.1:8000';
const AUTH_PATH = process.env.WWEBJS_AUTH_PATH || '/app/.wwebjs_auth';
const CHROME_PATH = process.env.PUPPETEER_EXECUTABLE_PATH || '/usr/bin/google-chrome-stable';

if (!MAIN_NUMBER || !WHATSAPP_LID || !WHATSAPP_PIN) {
    console.error('\nERROR: Missing required .env variables:');
    if (!MAIN_NUMBER) console.error('  - WHATSAPP_MAIN_NUMBER');
    if (!WHATSAPP_LID) console.error('  - WHATSAPP_LID (send the bot a message, then copy the "From:" number from the log)');
    if (!WHATSAPP_PIN) console.error('  - WHATSAPP_PIN');
    process.exit(1);
}

function digitsOnly(value) {
    return (value || '').replace(/@.*$/, '').replace(/:\d+$/, '').replace(/\D/g, '');
}

function toWhatsAppFormat(text) {
    return (text || '').replace(/\*\*(.+?)\*\*/g, '*$1*');
}

console.log('\n═══════════════════════════════════════════════════════');
console.log('PesaPilot WhatsApp Bot v1.2');
console.log('═══════════════════════════════════════════════════════');
console.log(`Phone Number : configured`);
console.log('LID          : configured');
console.log(`PIN          : configured`);
console.log(`API URL      : ${API_URL}`);
console.log(`Chrome       : ${CHROME_PATH}`);
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
        const qrServerUrl = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(qr)}`;
        console.log(`\nQR image link (third-party service, opt-in): ${qrServerUrl}\n`);
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
    console.log('\nCommands: Summary, Help, Bar chart, Pie chart, Trend');
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

client.on('message', async (message) => {
    try {
        const senderNumber = message.from;
        const userMessage = message.body.trim();
        const senderNumeric = digitsOnly(senderNumber);
        const mainNumeric = digitsOnly(MAIN_NUMBER);
        const lidNumeric = digitsOnly(WHATSAPP_LID);

        let isAuthorized = false;
        if (mainNumeric && senderNumeric === mainNumeric) isAuthorized = true;
        else if (lidNumeric && senderNumeric === lidNumeric) isAuthorized = true;
        else {
            try {
                const contact = await message.getContact();
                const contactNum = digitsOnly(contact.number);
                if ((mainNumeric && contactNum === mainNumeric) || (lidNumeric && contactNum === lidNumeric)) {
                    isAuthorized = true;
                }
            } catch (e) {}
        }

        console.log(`\nFrom: ${senderNumeric}`);
        console.log(`Msg: "${userMessage.substring(0, 50)}${userMessage.length > 50 ? '...' : ''}"`);

        if (!isAuthorized) {
            console.log('Non-main sender — leaving for manual reply');
            return;
        }

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
                const response = await axios.post(`${API_URL}/parse-sms`, { sms_content: smsContent }, { timeout: 20000 });
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
            const response = await axios.post(`${API_URL}/ask`, { question: userMessage }, { timeout: 30000 });

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
        try { await message.reply('❌ Something went wrong.'); } catch (e) {}
    }
});

client.on('disconnected', (reason) => {
    isReady = false;
    console.log(`\nDisconnected: ${reason}`);
    if (shuttingDown) return;
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
        const response = await axios.get(`${API_URL}/daily-summary`, { timeout: 20000 });
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
        const response = await axios.get(`${API_URL}/budget-check`, { timeout: 20000 });
        const alerts = response?.data?.alerts || [];

        if (alerts.length === 0) {
            console.log('Budget check: nothing new to report.\n');
            return;
        }

        for (const alert of alerts) {
            const icon = alert.alert_level === 'over' ? '🚨' : '⚠️';
            await client.sendMessage(DAILY_SUMMARY_CHAT_ID, `${icon} ${toWhatsAppFormat(alert.message)}`);
            await new Promise(resolve => setTimeout(resolve, 500));
        }
        console.log(`Sent ${alerts.length} budget alert(s)\n`);
    } catch (error) {
        console.error(`Budget check cron error: ${error.message}\n`);
    }
}, { timezone: 'Africa/Nairobi' });

console.log('Budget check scheduled every 2 hours (Africa/Nairobi)\n');

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