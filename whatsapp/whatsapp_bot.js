// whatsapp/whatsapp_bot.js - SECURE VERSION (Hidden env, trimmed output)
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
require('dotenv').config();

// ─── CONFIG ──────────────────────────────────────────────────────────────
const MAIN_NUMBER  = process.env.WHATSAPP_MAIN_NUMBER;
const WHATSAPP_LID = process.env.WHATSAPP_LID;
const WHATSAPP_PIN = process.env.WHATSAPP_PIN;
const API_URL      = process.env.WHATSAPP_API_URL || 'http://localhost:8000';

if (!MAIN_NUMBER || !WHATSAPP_LID || !WHATSAPP_PIN) {
  console.error('\n❌ ERROR: Missing .env variables');
  console.error('  - WHATSAPP_MAIN_NUMBER');
  console.error('  - WHATSAPP_LID');
  console.error('  - WHATSAPP_PIN');
  process.exit(1);
}

// ─── STARTUP (HIDE SENSITIVE INFO) ──────────────────────────────────────
console.log('\n═══════════════════════════════════════════════════════');
console.log('🤖 PesaPilot WhatsApp Bot v2.0');
console.log('═══════════════════════════════════════════════════════');
console.log(`✅ Phone Number : configured`);
console.log(`✅ LID          : configured`);
console.log(`✅ PIN          : configured`);
console.log(`🔗 API URL      : ${API_URL}`);
console.log('═══════════════════════════════════════════════════════\n');

// ─── CLIENT ──────────────────────────────────────────────────────────────
const client = new Client({
  authStrategy: new LocalAuth(),
  puppeteer: {
    headless: true,
    protocolTimeout: 120000,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
  }
});

// ─── QR CODE ─────────────────────────────────────────────────────────────
client.on('qr', (qr) => {
  console.log('\n╔════════════════════════════════════════════════════════╗');
  console.log('║        SCAN QR CODE WITH YOUR SPARE AIRTEL PHONE       ║');
  console.log('║  Settings → Linked Devices → Link a Device             ║');
  console.log('╚════════════════════════════════════════════════════════╝\n');
  qrcode.generate(qr, { small: true });
  console.log('\n⏳ Waiting for scan...\n');
});

// ─── READY ──────────────────────────────────────────────────────────────
client.on('ready', () => {
  console.log('\n╔═══════════════════════════════════════════════════════╗');
  console.log('║              ✅ BOT IS ONLINE!                        ║');
  console.log('╚═══════════════════════════════════════════════════════╝');
  console.log(`🤖 Bot ID: ${client.info.wid._serialized}`);
  console.log(`📞 Authorized: configured`);
  console.log(`🔗 API: ${API_URL}\n`);
  console.log('💡 Examples:');
  console.log('  📊 "Show me food spending as a pie chart"');
  console.log('  📊 "Bar chart of my transport expenses"');
  console.log('  📈 "Daily spending trend for this month"');
  console.log('  🏆 "Top 5 merchants bar chart"');
  console.log('  🔥 "Heatmap of my weekly spending"');
  console.log('  📊 "Summary" / "Help"\n');
});

// ─── MESSAGE HANDLER ────────────────────────────────────────────────────
client.on('message', async (message) => {
  try {
    const senderNumber = message.from;
    const userMessage  = message.body.trim();

    const senderNumeric = senderNumber.replace(/@.*$/, '');
    const mainNumeric   = MAIN_NUMBER.replace(/@.*$/, '');
    const lidNumeric    = WHATSAPP_LID.replace(/@.*$/, '');

    // ─── AUTHORIZE ──────────────────────────────────────────────────────
    let isAuthorized = false;
    if ((mainNumeric && senderNumeric === mainNumeric) || (lidNumeric && senderNumeric === lidNumeric)) {
      isAuthorized = true;
    } else {
      try {
        const contact = await message.getContact();
        const contactNum = (contact.number || '').replace(/@.*$/, '');
        if ((mainNumeric && contactNum === mainNumeric) || (lidNumeric && contactNum === lidNumeric)) {
          isAuthorized = true;
        }
      } catch (e) {}
    }

    // Log WITHOUT exposing sensitive info
    console.log(`\n📨 From: ${senderNumeric}`);
    console.log(`📝 Msg: "${userMessage.substring(0, 50)}${userMessage.length > 50 ? '...' : ''}"`);

    if (!isAuthorized) {
      console.log('⛔ Unauthorized');
      await message.reply('⛔ This number is not authorized.');
      try { await message.react('🚫'); } catch (e) {}
      return;
    }

    console.log('✅ Authorized');
    try { await message.react('⏳'); } catch (e) {}

    // ─── MANUAL SMS ENTRY ──────────────────────────────────────────────
    if (userMessage.startsWith(WHATSAPP_PIN + '-')) {
      console.log('📝 Manual SMS entry');
      const smsContent = userMessage.substring(WHATSAPP_PIN.length + 1).trim();

      if (!smsContent) {
        console.log('❌ Empty SMS');
        await message.reply('❌ Format: PIN-SMS_CONTENT');
        try { await message.react('❌'); } catch (e) {}
        return;
      }

      console.log(`📏 SMS: ${smsContent.length} chars`);

      try {
        console.log('🔄 Sending to API...');
        const response = await axios.post(`${API_URL}/parse-sms`, { sms_content: smsContent }, { timeout: 20000 });

        if (response.data.success) {
          console.log('✅ SMS stored');
          await message.reply(response.data.summary);
          try { await message.react('✅'); } catch (e) {}
        } else {
          console.log(`❌ Parse failed`);
          await message.reply(`❌ ${response.data.error}`);
          try { await message.react('❌'); } catch (e) {}
        }
      } catch (error) {
        console.error(`❌ API Error`);
        await message.reply('❌ Error processing SMS. Try again.');
        try { await message.react('❌'); } catch (e) {}
      }
      return;
    }

    // ─── QUESTIONS & CHARTS ────────────────────────────────────────────
    try {
      console.log('🔄 Processing...');
      const response = await axios.post(`${API_URL}/ask`, { question: userMessage }, { timeout: 30000 });

      // ─── CHART RESPONSE ──────────────────────────────────────────────
      if (response.data.chart) {
        console.log('📊 Sending chart...');
        try {
          const media = new MessageMedia('image/png', response.data.chart, 'chart.png');
          await client.sendMessage(message.from, media, { 
            caption: response.data.analysis || '📊 Chart' 
          });
          console.log('✅ Chart sent');
          try { await message.react('📊'); } catch (e) {}
        } catch (chartError) {
          console.error(`❌ Chart error`);
          await message.reply(`${response.data.analysis}\n\n(Chart unavailable)`);
          try { await message.react('✅'); } catch (e) {}
        }
        return;
      }

      // ─── TEXT RESPONSE (TRIM AI OUTPUT) ──────────────────────────────
      console.log('📝 Text response');
      let analysis = response.data.analysis || 'No response';

      // 🔥 TRIM AI OUTPUT - Limit to 1000 characters if too long
      const MAX_LENGTH = 1000;
      if (analysis.length > MAX_LENGTH) {
        analysis = analysis.substring(0, MAX_LENGTH) + '\n\n...(truncated)';
        console.log(`✂️ Trimmed ${analysis.length} chars`);
      }

      const chunks = splitMessage(analysis, 3000);

      for (let i = 0; i < chunks.length; i++) {
        await message.reply(chunks[i]);
        console.log(`📤 Sent ${i + 1}/${chunks.length}`);
      }

      console.log('✅ Done');
      try { await message.react('✅'); } catch (e) {}

    } catch (error) {
      console.error(`❌ Error`);
      if (error.response) {
        console.error(`   Status: ${error.response.status}`);
      }
      await message.reply('❌ Error processing your request.');
      try { await message.react('❌'); } catch (e) {}
    }

  } catch (error) {
    console.error(`❌ Fatal: ${error.message}`);
    try {
      await message.reply('❌ Something went wrong.');
      try { await message.react('❌'); } catch (e) {}
    } catch (e) {}
  }
});

// ─── DISCONNECTED ────────────────────────────────────────────────────────
client.on('disconnected', (reason) => {
  console.log(`\n⚠️ Disconnected: ${reason}`);
});

// ─── HELPER ──────────────────────────────────────────────────────────────
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

// ─── START ───────────────────────────────────────────────────────────────
client.initialize();

process.on('SIGINT',  async () => { console.log('\n👋 Shutting down...'); await client.destroy(); process.exit(0); });
process.on('SIGTERM', async () => { console.log('\n👋 Shutting down...'); await client.destroy(); process.exit(0); });