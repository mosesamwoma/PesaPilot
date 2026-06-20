const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

// ═══════════════════════════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════════════════════════
const MAIN_NUMBER = process.env.WHATSAPP_MAIN_NUMBER;
const WHATSAPP_LID = process.env.WHATSAPP_LID;
const WHATSAPP_PIN = process.env.WHATSAPP_PIN;
const API_URL = process.env.WHATSAPP_API_URL || 'http://localhost:8000';

if (!MAIN_NUMBER || !WHATSAPP_LID || !WHATSAPP_PIN) {
    console.error('\n❌ ERROR: Missing required .env variables:');
    if (!MAIN_NUMBER) console.error('  - WHATSAPP_MAIN_NUMBER');
    if (!WHATSAPP_LID) console.error('  - WHATSAPP_LID');
    if (!WHATSAPP_PIN) console.error('  - WHATSAPP_PIN');
    process.exit(1);
}

console.log('\n═══════════════════════════════════════════════════════');
console.log('🤖 PesaPilot WhatsApp Bot v2.0');
console.log('═══════════════════════════════════════════════════════');
console.log(`✅ Phone Number : configured`);
console.log(`✅ LID          : configured`);
console.log(`✅ PIN          : configured`);
console.log(`🔗 API URL      : ${API_URL}`);
console.log('═══════════════════════════════════════════════════════\n');

// ═══════════════════════════════════════════════════════════════════════════════
// FIX: Use Simple Auth Strategy (prevents "browser already running" error)
// ═══════════════════════════════════════════════════════════════════════════════
const client = new Client({
    authStrategy: new LocalAuth({
        dataPath: '/app/.wwebjs_auth',
        clientId: 'pesapilot-session'
    }),
    puppeteer: {
        headless: true,
        protocolTimeout: 180000,  // Increased to 3 minutes
        timeout: 180000,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-accelerated-2d-canvas',
            '--disable-accelerated-video-decode',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-breakpad',
            '--disable-client-side-phishing-detection',
            '--disable-default-apps',
            '--disable-device-discovery-notifications',
            '--disable-extensions',
            '--disable-features=InterestFeedContentSuggestions',
            '--disable-sync',
            '--disable-translate',
            '--metrics-recording-only',
            '--mute-audio',
            '--no-default-browser-check',
            '--no-first-run',
            '--disable-blink-features=AutomationControlled',
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]
    }
});

// ═══════════════════════════════════════════════════════════════════════════════
// QR CODE EVENT
// ═══════════════════════════════════════════════════════════════════════════════
client.on('qr', (qr) => {
    console.log('\n╔════════════════════════════════════════════════════════╗');
    console.log('║        SCAN QR CODE WITH YOUR SPARE AIRTEL PHONE       ║');
    console.log('║  Settings → Linked Devices → Link a Device             ║');
    console.log('╚════════════════════════════════════════════════════════╝\n');
    qrcode.generate(qr, { small: true });
    console.log('\n⏳ Waiting for scan...\n');
});

// ═══════════════════════════════════════════════════════════════════════════════
// READY EVENT
// ═══════════════════════════════════════════════════════════════════════════════
client.on('ready', () => {
    console.log('\n╔═══════════════════════════════════════════════════════╗');
    console.log('║              ✅ BOT IS ONLINE!                        ║');
    console.log('╚═══════════════════════════════════════════════════════╝');
    console.log(`🤖 Bot WhatsApp ID : ${client.info.wid._serialized}`);
    console.log(`🔗 API             : ${API_URL}`);
    console.log('\n💬 Commands: Summary, Help, Bar chart, Pie chart, Trend');
    console.log('👋 Greetings: Good morning, Hello, Hi\n');
    console.log(`📝 Manual entry: PIN-SMS_CONTENT\n`);
});

// ═══════════════════════════════════════════════════════════════════════════════
// MESSAGE HANDLER
// ═══════════════════════════════════════════════════════════════════════════════
client.on('message', async (message) => {
    try {
        const senderNumber = message.from;
        const userMessage = message.body.trim();
        const senderNumeric = senderNumber.replace(/@.*$/, '');
        const mainNumeric = MAIN_NUMBER.replace(/@.*$/, '');
        const lidNumeric = WHATSAPP_LID.replace(/@.*$/, '');

        let isAuthorized = false;
        if (mainNumeric && senderNumeric === mainNumeric) isAuthorized = true;
        else if (lidNumeric && senderNumeric === lidNumeric) isAuthorized = true;
        else {
            try {
                const contact = await message.getContact();
                const contactNum = (contact.number || '').replace(/@.*$/, '');
                if ((mainNumeric && contactNum === mainNumeric) || (lidNumeric && contactNum === lidNumeric)) {
                    isAuthorized = true;
                }
            } catch (e) {}
        }

        console.log(`\n📨 From: ${senderNumeric}`);
        console.log(`📝 Msg: "${userMessage.substring(0, 50)}${userMessage.length > 50 ? '...' : ''}"`);

        if (!isAuthorized) {
            console.log('⛔ Unauthorized');
            await message.reply('⛔ This number is not authorized.');
            return;
        }

        console.log('✅ Authorized');
        try { await message.react('⏳'); } catch (e) {}

        // ─── MANUAL SMS ENTRY ──────────────────────────────────────────────
        if (userMessage.startsWith(WHATSAPP_PIN + '-')) {
            console.log('📝 Manual SMS entry');
            const smsContent = userMessage.substring(WHATSAPP_PIN.length + 1).trim();
            if (!smsContent) {
                await message.reply('❌ Format: PIN-SMS_CONTENT');
                return;
            }
            try {
                const response = await axios.post(`${API_URL}/parse-sms`, { sms_content: smsContent }, { timeout: 20000 });
                if (response.data.success) {
                    await message.reply(response.data.summary);
                    try { await message.react('✅'); } catch (e) {}
                } else {
                    await message.reply(`❌ ${response.data.error}`);
                    try { await message.react('❌'); } catch (e) {}
                }
            } catch (error) {
                await message.reply('❌ Error processing SMS.');
                try { await message.react('❌'); } catch (e) {}
            }
            return;
        }

        // ─── QUESTIONS & CHARTS ────────────────────────────────────────────
        try {
            const response = await axios.post(`${API_URL}/ask`, { question: userMessage }, { timeout: 30000 });

            if (response.data.chart) {
                try {
                    const media = new MessageMedia('image/png', response.data.chart, 'chart.png');
                    await client.sendMessage(message.from, media, { caption: response.data.analysis || '📊 Chart' });
                    try { await message.react('📊'); } catch (e) {}
                } catch (chartError) {
                    await message.reply(`${response.data.analysis}\n\n(Chart unavailable)`);
                    try { await message.react('✅'); } catch (e) {}
                }
                return;
            }

            let analysis = response.data.analysis || 'No response';
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
            console.error(`❌ Error: ${error.message}`);
            await message.reply('❌ Error processing your request.');
            try { await message.react('❌'); } catch (e) {}
        }

    } catch (error) {
        console.error(`❌ Fatal: ${error.message}`);
        try { await message.reply('❌ Something went wrong.'); } catch (e) {}
    }
});

// ═══════════════════════════════════════════════════════════════════════════════
// DISCONNECTED
// ═══════════════════════════════════════════════════════════════════════════════
client.on('disconnected', (reason) => {
    console.log(`\n⚠️ Disconnected: ${reason}`);
    console.log('🔄 Attempting to reconnect...\n');
});

// ═══════════════════════════════════════════════════════════════════════════════
// HELPER
// ═══════════════════════════════════════════════════════════════════════════════
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

// ═══════════════════════════════════════════════════════════════════════════════
// START
// ═══════════════════════════════════════════════════════════════════════════════
console.log('Initializing WhatsApp client...\n');
client.initialize();

process.on('SIGINT', async () => {
    console.log('\n👋 Shutting down...');
    await client.destroy();
    process.exit(0);
});
process.on('SIGTERM', async () => {
    console.log('\n👋 Shutting down...');
    await client.destroy();
    process.exit(0);
});