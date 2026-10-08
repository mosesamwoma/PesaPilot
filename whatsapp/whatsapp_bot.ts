import {
    makeWASocket,
    useMultiFileAuthState,
    fetchLatestBaileysVersion,
    DisconnectReason,
    normalizeMessageContent,
    proto,
} from '@whiskeysockets/baileys';
import type { WASocket } from '@whiskeysockets/baileys';
import { Boom } from '@hapi/boom';
import pino from 'pino';
import qrcodeTerminal from 'qrcode-terminal';
import axios, { AxiosError } from 'axios';
import cron from 'node-cron';
import fs from 'fs';
import dotenv from 'dotenv';


interface Config {
    mainNumber: string;
    whatsappLid: string;
    whatsappPin: string;
    apiUrl: string;
    authPath: string;
    usePairingCode: boolean;
    showQrLink: boolean;
    logLevel: string;
}

interface MessageResponse {
    analysis?: string;
    chart?: string;
    error?: string;
}

interface DailySummaryResponse {
    summary: string;
}

type QuotableMessage = proto.IWebMessageInfo & { key: proto.IMessageKey };

interface BudgetAlert {
    category: string;
    alert_level: 'warning' | 'over';
    message: string;
}

interface BudgetAlertsResponse {
    alerts: BudgetAlert[];
    count: number;
}

interface ParseSMSResponse {
    success: boolean;
    summary: string;
    error?: string;
}


dotenv.config();


const config: Config = {
    mainNumber: process.env.WHATSAPP_MAIN_NUMBER || '',
    whatsappLid: process.env.WHATSAPP_LID || '',
    whatsappPin: process.env.WHATSAPP_PIN || '',
    apiUrl: process.env.API_URL || 'http://127.0.0.1:8000',
    authPath: process.env.BAILEYS_AUTH_PATH || './.baileys_auth',
    usePairingCode: (process.env.WHATSAPP_USE_PAIRING_CODE || 'false').toLowerCase() === 'true',
    showQrLink: (process.env.WHATSAPP_QR_LINK || 'false').toLowerCase() === 'true',
    logLevel: process.env.BAILEYS_LOG_LEVEL || 'info',
};


function validateConfig(config: Config): void {
    if (!config.mainNumber) {
        console.error('\n❌ ERROR: WHATSAPP_MAIN_NUMBER is required in .env');
        process.exit(1);
    }

    if (!config.whatsappLid) {
        console.warn('\n⚠️  WHATSAPP_LID is not set. Messages from linked-device IDs will be ignored until you add it.');
        console.warn('   Send the bot a message, then copy the "From:" number from the log into WHATSAPP_LID.\n');
    }

    if (!config.whatsappPin) {
        console.error('\n❌ ERROR: WHATSAPP_PIN is required in .env');
        process.exit(1);
    }
}

validateConfig(config);


function printBanner(config: Config): void {
    console.log('\n═══════════════════════════════════════════════════════');
    console.log('🤖 PesaPilot WhatsApp Bot v1.2 (Baileys TypeScript)');
    console.log('═══════════════════════════════════════════════════════');
    console.log(`✅ Phone Number : configured`);
    console.log(`${config.whatsappLid ? '✅' : '⚠️ '} LID          : ${config.whatsappLid ? 'configured' : 'not set'}`);
    console.log(`✅ PIN          : configured`);
    console.log(`🔗 API URL      : ${config.apiUrl}`);
    console.log(`📂 Auth path    : ${config.authPath}`);
    console.log(`🔑 Login mode   : ${config.usePairingCode ? 'Pairing code' : 'QR code'}`);
    console.log(`📊 Log level    : ${config.logLevel}`);
    console.log('═══════════════════════════════════════════════════════\n');
}

printBanner(config);


function ensureAuthDirectory(authPath: string): void {
    try {
        fs.mkdirSync(authPath, { recursive: true });
        console.log(`✅ Auth directory ready: ${authPath}`);
    } catch (error) {
        const err = error as Error;
        console.error(`❌ Failed to create auth directory: ${err.message}`);
        process.exit(1);
    }
}

ensureAuthDirectory(config.authPath);


const logger = pino({
    level: config.logLevel,
});


function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function stripSuffix(jid: string): string {
    return (jid || '').replace(/@.*$/, '');
}

function toWhatsAppFormat(text: string): string {
    return (text || '').replace(/\*\*(.+?)\*\*/g, '*$1*');
}

function extractText(msg: proto.IWebMessageInfo): string {
    const m = normalizeMessageContent(msg.message);
    if (!m) return '';

    if (m.conversation) return m.conversation;
    if (m.extendedTextMessage?.text) return m.extendedTextMessage.text;
    if (m.imageMessage?.caption) return m.imageMessage.caption;
    if (m.videoMessage?.caption) return m.videoMessage.caption;
    if (m.buttonsResponseMessage?.selectedButtonId) return m.buttonsResponseMessage.selectedButtonId;
    if (m.listResponseMessage?.singleSelectReply?.selectedRowId) return m.listResponseMessage.singleSelectReply.selectedRowId;
    if (m.buttonsResponseMessage?.selectedDisplayText) return m.buttonsResponseMessage.selectedDisplayText;

    return '';
}

async function react(sock: WASocket, jid: string, key: proto.IMessageKey, emoji: string): Promise<void> {
    try {
        await sock.sendMessage(jid, { react: { text: emoji, key } });
    } catch (e) {
    }
}

function splitMessage(text: string, maxLength: number): string[] {
    if (text.length <= maxLength) return [text];

    const chunks: string[] = [];
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

function isAuthorized(
    senderNumeric: string,
    mainNumber: string,
    lidNumber: string
): boolean {
    const mainNumeric = stripSuffix(mainNumber);
    const lidNumeric = stripSuffix(lidNumber);

    if (mainNumeric && senderNumeric === mainNumeric) return true;
    if (lidNumeric && senderNumeric === lidNumeric) return true;

    return false;
}


let currentSock: WASocket | null = null;
let isConnected = false;
let startupResolved = false;
let shuttingDown = false;

const STARTUP_TIMEOUT_MS = 120 * 1000;

const startupWatchdog = setTimeout(() => {
    if (!startupResolved) {
        console.error(`\n❌ No QR/pairing code or open connection after ${STARTUP_TIMEOUT_MS / 1000}s.`);
        console.error('   Exiting so the container restarts.\n');
        process.exit(1);
    }
}, STARTUP_TIMEOUT_MS);

startupWatchdog.unref();


async function callApi<T>(endpoint: string, method: 'GET' | 'POST' = 'GET', data?: any): Promise<T> {
    const url = `${config.apiUrl}${endpoint}`;
    try {
        const response = await axios({
            method,
            url,
            data,
            timeout: 30000,
            headers: {
                'Content-Type': 'application/json',
            },
        });
        return response.data;
    } catch (error) {
        const err = error as AxiosError;
        if (err.code === 'ECONNREFUSED') {
            throw new Error('API server is not running. Please start the API server.');
        }
        throw error;
    }
}

async function handleManualSms(smsContent: string, sock: WASocket, jid: string, msg: QuotableMessage): Promise<void> {
    console.log('📝 Manual SMS entry');

    if (!smsContent) {
        await sock.sendMessage(jid, { text: '❌ Format: PIN-SMS_CONTENT' }, { quoted: msg });
        return;
    }

    try {
        const response = await callApi<ParseSMSResponse>('/parse-sms', 'POST', { sms_content: smsContent });
        if (response.success) {
            await sock.sendMessage(jid, { text: toWhatsAppFormat(response.summary) }, { quoted: msg });
            await react(sock, jid, msg.key, '✅');
        } else {
            await sock.sendMessage(
                jid,
                { text: response.summary || (response.error ? `❌ ${response.error}` : '❌ Could not parse SMS') },
                { quoted: msg }
            );
            await react(sock, jid, msg.key, '❌');
        }
    } catch (error) {
        const err = error as Error;
        console.error(`❌ SMS error: ${err.message}`);
        await sock.sendMessage(jid, { text: '❌ Error processing SMS.' }, { quoted: msg });
        await react(sock, jid, msg.key, '❌');
    }
}

async function handleQuestion(userMessage: string, sock: WASocket, jid: string, msg: QuotableMessage): Promise<void> {
    try {
        const response = await callApi<MessageResponse>('/ask', 'POST', { question: userMessage });

        if (response.chart) {
            const analysisText = toWhatsAppFormat(response.analysis || '');
            const CAPTION_LIMIT = 1000;
            try {
                const buffer = Buffer.from(response.chart, 'base64');
                const captionFits = analysisText.length <= CAPTION_LIMIT;
                await sock.sendMessage(
                    jid,
                    { image: buffer, caption: captionFits ? (analysisText || '📊 Chart') : '📊 Chart' },
                    { quoted: msg }
                );
                if (!captionFits) {
                    for (const chunk of splitMessage(analysisText.substring(0, 4000), 3000)) {
                        await sock.sendMessage(jid, { text: chunk }, { quoted: msg });
                        await sleep(500);
                    }
                }
                await react(sock, jid, msg.key, '📊');
            } catch (chartError) {
                await sock.sendMessage(
                    jid,
                    { text: `${analysisText}\n\n(Chart unavailable)` },
                    { quoted: msg }
                );
                await react(sock, jid, msg.key, '✅');
            }
            return;
        }

        let analysis = toWhatsAppFormat(response.analysis || 'No response');
        if (analysis.length > 4000) {
            analysis = analysis.substring(0, 4000) + '\n\n...(truncated)';
        }

        const chunks = splitMessage(analysis, 3000);
        for (let i = 0; i < chunks.length; i++) {
            await sock.sendMessage(jid, { text: chunks[i] }, { quoted: msg });
            if (i < chunks.length - 1) await sleep(500);
        }
        await react(sock, jid, msg.key, '✅');

    } catch (error) {
        const err = error as Error;
        console.error(`❌ Error: ${err.message}`);
        await sock.sendMessage(
            jid,
            { text: err.message.includes('API server') ? `❌ ${err.message}` : '❌ Error processing your request.' },
            { quoted: msg }
        );
        await react(sock, jid, msg.key, '❌');
    }
}


async function handleMessage(
    msg: proto.IWebMessageInfo,
    sock: WASocket
): Promise<void> {
    try {
        if (!msg.message) return;
        if (!msg.key || msg.key.fromMe) return;
        const key = msg.key;

        const jid = key.remoteJid;
        if (!jid || jid === 'status@broadcast' || jid.endsWith('@g.us') || jid.endsWith('@broadcast')) return;

        const userMessage = extractText(msg).trim();
        if (!userMessage) return;

        const senderNumeric = stripSuffix(jid);
        const authorized = isAuthorized(
            senderNumeric,
            config.mainNumber,
            config.whatsappLid
        );

        console.log(`\n📨 From: ${senderNumeric}`);
        console.log(`📝 Msg: "${userMessage.substring(0, 50)}${userMessage.length > 50 ? '...' : ''}"`);

        if (!authorized) {
            console.log('👤 Non-main sender — leaving for manual reply');
            return;
        }

        console.log('✅ Authorized');
        await react(sock, jid, key, '⏳');

        const quotableMsg: QuotableMessage = { ...msg, key };

        if (userMessage.startsWith(config.whatsappPin + '-')) {
            const smsContent = userMessage.substring(config.whatsappPin.length + 1).trim();
            await handleManualSms(smsContent, sock, jid, quotableMsg);
            return;
        }

        await handleQuestion(userMessage, sock, jid, quotableMsg);

    } catch (error) {
        const err = error as Error;
        console.error(`❌ Fatal: ${err.message}`);
        try {
            const remoteJid = msg.key?.remoteJid;
            if (remoteJid) {
                await sock.sendMessage(remoteJid, { text: '❌ Something went wrong.' });
            }
        } catch (e) {
        }
    }
}


async function startBaileys(): Promise<WASocket> {
    console.log('🔄 Initializing WhatsApp client...\n');

    try {
        const { state, saveCreds } = await useMultiFileAuthState(config.authPath);
        console.log('✅ Auth state loaded');

        let waVersion: [number, number, number];
        try {
            const { version, isLatest } = await fetchLatestBaileysVersion();
            waVersion = version;
            console.log(`✅ Using WA web version: ${version.join('.')} (latest: ${isLatest})`);
        } catch (e) {
            console.warn(`⚠️  Could not fetch latest WA version, using Baileys default: ${(e as Error).message}`);
            waVersion = [2, 3000, 1023223821];
        }

        const sock = makeWASocket({
            auth: state,
            logger,
            version: waVersion,
            browser: ['Ubuntu', 'Chrome', '120.0.0'],
            syncFullHistory: false,
            markOnlineOnConnect: false,
            generateHighQualityLinkPreview: false,
        });

        currentSock = sock;
        console.log('✅ Socket created');

        sock.ev.on('creds.update', saveCreds);

        let pairingCodeRequested = false;

        sock.ev.on('connection.update', async (update) => {
            const { connection, lastDisconnect, qr } = update;

            if (qr && config.usePairingCode && !pairingCodeRequested && !state.creds.registered) {
                pairingCodeRequested = true;
                try {
                    console.log('📱 Requesting pairing code...');
                    const code = await sock.requestPairingCode(config.mainNumber);
                    startupResolved = true;
                    console.log('\n╔════════════════════════════════════════════════════════╗');
                    console.log('║          ENTER THIS PAIRING CODE ON YOUR PHONE         ║');
                    console.log('║  Settings → Linked Devices → Link with phone number    ║');
                    console.log('╚════════════════════════════════════════════════════════╝\n');
                    console.log(`🔑 Pairing code: ${code}\n`);
                    console.log('⏳ Waiting for connection...\n');
                } catch (e) {
                    const err = e as Error;
                    console.error(`❌ Failed to request pairing code: ${err.message}`);
                    pairingCodeRequested = false;
                }
            }

            if (qr && !config.usePairingCode) {
                startupResolved = true;
                console.log('\n╔════════════════════════════════════════════════════════╗');
                console.log('║        SCAN QR CODE WITH YOUR SPARE AIRTEL PHONE       ║');
                console.log('║  Settings → Linked Devices → Link a Device             ║');
                console.log('╚════════════════════════════════════════════════════════╝\n');

                try {
                    console.log('📱 QR Code (scan with WhatsApp):');
                    qrcodeTerminal.generate(qr, { small: true });
                } catch (e) {
                    console.warn(`⚠️  QR rendering error: ${(e as Error).message}`);
                }

                if (config.showQrLink) {
                    const qrServerUrl = `https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=${encodeURIComponent(qr)}`;
                    console.log(`\n🔗 QR image link (third-party service, opt-in):\n${qrServerUrl}\n`);
                } else {
                    console.log('\n💡 QR unreadable in your terminal? Set WHATSAPP_USE_PAIRING_CODE=true to link with a code instead.');
                }
                console.log('⏳ Waiting for scan (scan within 2 minutes)...\n');
            }

            if (connection === 'open') {
                startupResolved = true;
                isConnected = true;
                console.log('\n╔═══════════════════════════════════════════════════════╗');
                console.log('║              ✅ BOT IS ONLINE!                        ║');
                console.log('╚═══════════════════════════════════════════════════════╝');
                console.log(`🤖 Bot WhatsApp ID : ${sock.user?.id || 'Unknown'}`);
                console.log(`🔗 API             : ${config.apiUrl}`);
                console.log('\n💬 Commands: Summary, Help, Bar chart, Pie chart, Trend');
                console.log(`📝 Manual entry: PIN-SMS_CONTENT\n`);
            }

            if (connection === 'close') {
                isConnected = false;
                const statusCode = lastDisconnect?.error instanceof Boom
                    ? lastDisconnect.error.output?.statusCode
                    : undefined;
                const loggedOut = statusCode === DisconnectReason.loggedOut;

                if (loggedOut) {
                    console.error('\n❌ Session logged out. Clearing auth so you can re-pair.');
                    console.error('   Exiting; the container restart will show a fresh QR/pairing code.\n');
                    try {
                        for (const entry of fs.readdirSync(config.authPath)) {
                            fs.rmSync(`${config.authPath}/${entry}`, { recursive: true, force: true });
                        }
                    } catch (e) {
                        console.warn(`⚠️  Could not clear auth: ${(e as Error).message}`);
                    }
                    process.exit(1);
                }

                if (shuttingDown) return;

                console.log(`\n⚠️ Disconnected (status ${statusCode ?? 'unknown'}). Reconnecting in 5s...\n`);
                setTimeout(() => {
                    startBaileys().catch((err) => {
                        console.error(`❌ Reconnect failed: ${(err as Error).message}`);
                        process.exit(1);
                    });
                }, 5000);
            }
        });

        sock.ev.on('messages.upsert', async ({ messages, type }) => {
            if (type !== 'notify') return;

            for (const msg of messages) {
                await handleMessage(msg, sock);
            }
        });

        console.log('✅ Bot is ready and waiting for messages...\n');
        return sock;

    } catch (error) {
        const err = error as Error;
        console.error(`❌ Failed to start Baileys: ${err.message}`);
        console.error(err.stack);
        throw error;
    }
}


function setupDailySummary(): void {
    const mainNumericGlobal = stripSuffix(config.mainNumber);
    const DAILY_SUMMARY_JID = config.mainNumber.includes('@')
        ? config.mainNumber
        : `${mainNumericGlobal}@s.whatsapp.net`;

    cron.schedule('0 21 * * *', async () => {
        console.log('\n⏰ Running scheduled daily summary job (21:00 Africa/Nairobi)...');
        if (!currentSock || !isConnected) {
            console.warn('⚠️  Skipped: bot is not currently connected.\n');
            return;
        }
        try {
            const response = await callApi<DailySummaryResponse>('/daily-summary');
            const summaryText = response?.summary || '⚠️ Could not generate summary.';
            await currentSock.sendMessage(DAILY_SUMMARY_JID, { text: toWhatsAppFormat(summaryText) });
            console.log('✅ Daily summary sent successfully\n');
        } catch (error) {
            const err = error as Error;
            console.error(`❌ Daily summary cron error: ${err.message}\n`);
        }
    }, { timezone: 'Africa/Nairobi' });

    console.log('📅 Daily summary scheduled for 9:00 PM Africa/Nairobi every day\n');
}

setupDailySummary();


function setupBudgetCheck(): void {
    const mainNumericGlobal = stripSuffix(config.mainNumber);
    const BUDGET_ALERT_JID = config.mainNumber.includes('@')
        ? config.mainNumber
        : `${mainNumericGlobal}@s.whatsapp.net`;

    cron.schedule('0 */2 * * *', async () => {
        console.log('\n⏰ Running scheduled budget check job...');
        if (!currentSock || !isConnected) {
            console.warn('⚠️  Skipped: bot is not currently connected.\n');
            return;
        }
        try {
            const response = await callApi<BudgetAlertsResponse>('/budget-check');
            const alerts = response?.alerts || [];

            if (alerts.length === 0) {
                console.log('✅ Budget check: nothing new to report.\n');
                return;
            }

            for (const alert of alerts) {
                const icon = alert.alert_level === 'over' ? '🚨' : '⚠️';
                await currentSock.sendMessage(BUDGET_ALERT_JID, {
                    text: `${icon} ${toWhatsAppFormat(alert.message)}`,
                });
                await sleep(500);
            }
            console.log(`✅ Sent ${alerts.length} budget alert(s)\n`);
        } catch (error) {
            const err = error as Error;
            console.error(`❌ Budget check cron error: ${err.message}\n`);
        }
    }, { timezone: 'Africa/Nairobi' });

    console.log('📅 Budget check scheduled every 2 hours (Africa/Nairobi)\n');
}

setupBudgetCheck();


async function shutdown(signal: string, exitCode = 0): Promise<void> {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(`\n👋 Received ${signal}, shutting down...`);
    try {
        if (currentSock) {
            await currentSock.end(undefined);
        }
    } catch (e) {
        console.warn(`⚠️  Error during shutdown: ${(e as Error).message}`);
    }
    process.exit(exitCode);
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

process.on('unhandledRejection', (reason) => {
    console.error('❌ Unhandled promise rejection:', reason);
});

process.on('uncaughtException', (err) => {
    console.error('❌ Uncaught exception:', err);
    shutdown('uncaughtException', 1);
});


console.log('🚀 Starting WhatsApp client...\n');

startBaileys().catch((err) => {
    console.error(`❌ startBaileys() failed: ${(err as Error).message}`);
    console.error((err as Error).stack);
    process.exit(1);
});