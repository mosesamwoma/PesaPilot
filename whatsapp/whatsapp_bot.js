// whatsapp_bot.js
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');

// ⚙️ CONFIGURATION — Change this to YOUR main Safaricom number
const MY_NUMBER = "254712345678@c.us";  // Format: country code + number + @c.us
const API_URL = "http://localhost:8000";

const client = new Client({
  authStrategy: new LocalAuth(),
  puppeteer: {
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage'
    ]
  }
});

// ──────────────────────────────────────────────────────────────────────────
// QR Code Scanning
// ──────────────────────────────────────────────────────────────────────────

client.on('qr', (qr) => {
  console.log('\n╔════════════════════════════════════════════════════════╗');
  console.log('║          SCAN QR CODE WITH YOUR AIRTEL PHONE           ║');
  console.log('║  Go to: Settings → Linked Devices → Link a Device      ║');
  console.log('╚════════════════════════════════════════════════════════╝\n');
  qrcode.generate(qr, { small: true });
});

// ──────────────────────────────────────────────────────────────────────────
// Connected
// ──────────────────────────────────────────────────────────────────────────

client.on('ready', () => {
  console.log('\n✅ WhatsApp bot is online!');
  console.log(`🤖 Bot running on Airtel number`);
  console.log(`📞 Listening for messages from: ${MY_NUMBER}`);
  console.log(`🔗 API: ${API_URL}`);
  console.log('\nWaiting for messages...\n');
});

// ──────────────────────────────────────────────────────────────────────────
// Incoming Messages
// ──────────────────────────────────────────────────────────────────────────

client.on('message', async (message) => {
  const senderNumber = message.from;
  const userMessage = message.body.trim();

  // Only respond to YOUR main number
  if (senderNumber !== MY_NUMBER) {
    console.log(`\n❌ Rejected message from unknown number: ${senderNumber}`);
    await message.reply('This number is not available. Please contact me on my main Safaricom number.');
    return;
  }

  console.log(`\n📨 Message from you: "${userMessage}"`);

  // Show typing indicator
  await client.sendPresenceSubscription(senderNumber);
  await message.react('⏳');

  try {
    // Send to Python API
    console.log('🔄 Querying AI...');
    const response = await axios.post(`${API_URL}/ask`, {
      question: userMessage
    }, {
      timeout: 30000
    });

    const analysis = response.data.analysis;

    // Split long messages (WhatsApp limit is ~4096 chars but be safe)
    const chunks = splitMessage(analysis, 3000);

    for (const chunk of chunks) {
      await message.reply(chunk);
      console.log(`📤 Sent: ${chunk.substring(0, 50)}...`);
    }

    await message.react('✅');

  } catch (error) {
    console.error('❌ Error:', error.message);
    const errorMsg = `Sorry, I couldn't process that. Error: ${error.message}`;
    await message.reply(errorMsg);
    await message.react('❌');
  }
});

// ──────────────────────────────────────────────────────────────────────────
// Connection Lost
// ──────────────────────────────────────────────────────────────────────────

client.on('disconnected', (reason) => {
  console.log(`\n⚠️  Bot disconnected: ${reason}`);
  console.log('Attempting to reconnect...\n');
});

// ──────────────────────────────────────────────────────────────────────────
// Helper Functions
// ──────────────────────────────────────────────────────────────────────────

function splitMessage(text, maxLength) {
  if (text.length <= maxLength) {
    return [text];
  }

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

// ──────────────────────────────────────────────────────────────────────────
// Start Bot
// ──────────────────────────────────────────────────────────────────────────

client.initialize();

// Graceful shutdown
process.on('SIGINT', async () => {
  console.log('\n\n👋 Shutting down bot...');
  await client.destroy();
  process.exit(0);
});