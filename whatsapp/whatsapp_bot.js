// whatsapp_bot.js
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');

// ⚙️ CONFIGURATION
const ALLOWED_NUMBERS = [
  "254715755649",  // Your main Safaricom number
  "715755649",     // Without country code
  "0715755649",    // With leading zero
  "115831308570778", // The LID from your Safaricom phone
];
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
  console.log('║        SCAN QR CODE WITH YOUR SPARE AIRTEL PHONE       ║');
  console.log('║  Go to: Settings → Linked Devices → Link a Device      ║');
  console.log('║  This keeps your main Safaricom number safe!           ║');
  console.log('╚════════════════════════════════════════════════════════╝\n');
  qrcode.generate(qr, { small: true });
});

// ──────────────────────────────────────────────────────────────────────────
// Connected
// ──────────────────────────────────────────────────────────────────────────

client.on('ready', () => {
  console.log('\n✅ WhatsApp bot is online!');
  console.log(`🤖 Bot running on SPARE Airtel number`);
  console.log(`📞 Bot WhatsApp ID: ${client.info.wid._serialized}`);
  console.log(`📞 Listening for messages from MAIN Safaricom`);
  console.log(`📞 Allowed: ${ALLOWED_NUMBERS.join(', ')}`);
  console.log(`🔗 API: ${API_URL}`);
  console.log('\n💡 Send a message FROM your Safaricom phone TO the Airtel number\n');
});

// ──────────────────────────────────────────────────────────────────────────
// Incoming Messages
// ──────────────────────────────────────────────────────────────────────────

client.on('message', async (message) => {
  const senderNumber = message.from;
  const userMessage = message.body.trim();

  console.log('\n🔍 === DEBUG SENDER INFO ===');
  console.log(`Full sender ID: ${senderNumber}`);
  console.log(`Message to: ${message.to}`);
  console.log(`Is from me: ${message.fromMe}`);
  console.log('=============================\n');

  // Extract numeric part from sender
  const senderNumeric = senderNumber.replace(/@.*$/, '');
  console.log(`📱 Sender numeric: ${senderNumeric}`);

  // Check if sender is allowed
  let isAllowed = false;
  for (const num of ALLOWED_NUMBERS) {
    if (senderNumeric === num || senderNumeric.includes(num) || num.includes(senderNumeric)) {
      isAllowed = true;
      console.log(`✅ Matched: ${senderNumeric} === ${num}`);
      break;
    }
  }

  // If still not allowed, try to get contact info
  if (!isAllowed) {
    try {
      const contact = await message.getContact();
      console.log(`📇 Contact number: ${contact.number}`);
      console.log(`📇 Contact name: ${contact.name || 'Unknown'}`);
      
      // Check if contact number matches allowed numbers
      for (const num of ALLOWED_NUMBERS) {
        if (contact.number && (contact.number === num || contact.number.includes(num) || num.includes(contact.number))) {
          isAllowed = true;
          console.log(`✅ Matched contact: ${contact.number}`);
          break;
        }
      }
    } catch (err) {
      console.log('Could not get contact info');
    }
  }

  if (!isAllowed) {
    console.log(`\n❌ Rejected message from: ${senderNumber}`);
    console.log(`💡 Got: ${senderNumeric}`);
    console.log(`💡 Allowed: ${ALLOWED_NUMBERS.join(', ')}`);
    await message.reply('This number is not authorized. Please contact me on my main Safaricom number.');
    return;
  }

  console.log(`\n📨 Message from MAIN Safaricom: "${userMessage}"`);

  // Show typing indicator (simulate typing)
  await message.react('⏳');

  try {
    // Send to Python API
    console.log('🔄 Querying PesaPilot API...');
    const response = await axios.post(`${API_URL}/ask`, {
      question: userMessage
    }, {
      timeout: 30000
    });

    const analysis = response.data.analysis;

    // Split long messages
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