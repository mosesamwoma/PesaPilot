// whatsapp/whatsapp_bot.js - COMPLETE WORKING CODE (With LID)
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
require('dotenv').config();

// ⚙️ CONFIGURATION - Load from environment
const MAIN_NUMBER = process.env.WHATSAPP_MAIN_NUMBER || '115831308570778';
const API_URL = process.env.WHATSAPP_API_URL || 'http://localhost:8000';
const API_PORT = process.env.WHATSAPP_API_PORT || 8000;

console.log('\n═══════════════════════════════════════════════════════');
console.log('🤖 PesaPilot WhatsApp Bot');
console.log('═══════════════════════════════════════════════════════');
console.log(`📱 Main Number/LID: ${MAIN_NUMBER}`);
console.log(`🔗 API URL: ${API_URL}`);
console.log('═══════════════════════════════════════════════════════\n');

const client = new Client({
  authStrategy: new LocalAuth(),
  puppeteer: {
    headless: true,
    protocolTimeout: 120000,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu'
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
  console.log('\n⏳ Waiting for scan...\n');
});

// ──────────────────────────────────────────────────────────────────────────
// Connected
// ──────────────────────────────────────────────────────────────────────────

client.on('ready', () => {
  console.log('\n╔═══════════════════════════════════════════════════════╗');
  console.log('║              ✅ BOT IS ONLINE!                       ║');
  console.log('╚═══════════════════════════════════════════════════════╝');
  console.log(`🤖 Bot WhatsApp ID: ${client.info.wid._serialized}`);
  console.log(`📞 Listening for messages from: ${MAIN_NUMBER}`);
  console.log(`🔗 API: ${API_URL}`);
  console.log('\n💡 Now send a message from your MAIN Safaricom number\n');
  console.log('Example messages:');
  console.log('  • "What did I spend on food?"');
  console.log('  • "How much did I send to Safaricom?"');
  console.log('  • "Summary"');
  console.log('  • "Help"\n');
});

// ──────────────────────────────────────────────────────────────────────────
// Incoming Messages - MAIN LOGIC
// ──────────────────────────────────────────────────────────────────────────

client.on('message', async (message) => {
  try {
    const senderNumber = message.from;
    const userMessage = message.body.trim();

    console.log(`\n📨 Message received: "${userMessage.substring(0, 50)}..."`);

    // Extract numeric part (works with both @c.us and @lid)
    const senderNumeric = senderNumber.replace(/@.*$/, '');
    const mainNumeric = MAIN_NUMBER.replace(/@.*$/, '');

    console.log(`📱 From: ${senderNumeric}`);
    console.log(`📱 Allowed: ${mainNumeric}`);

    // Check if sender is authorized
    let isAuthorized = false;

    // Direct match
    if (senderNumeric === mainNumeric) {
      isAuthorized = true;
      console.log(`✅ Direct match!`);
    }

    // Try getting contact info as backup
    if (!isAuthorized) {
      try {
        const contact = await message.getContact();
        const contactNum = (contact.number || '').replace(/@.*$/, '');
        console.log(`👤 Contact: ${contact.name || 'Unknown'} (${contactNum})`);
        
        if (contactNum === mainNumeric) {
          isAuthorized = true;
          console.log(`✅ Contact match!`);
        }
      } catch (e) {
        console.log('⚠️  Could not get contact info');
      }
    }

    if (!isAuthorized) {
      console.log(`❌ Unauthorized: ${senderNumber}`);
      await message.reply('⛔ This number is not authorized.');
      await message.react('🚫');
      return;
    }

    // Show typing indicator
    await message.react('⏳');

    // Send to Python API
    console.log('🔄 Querying AI...');
    
    const response = await axios.post(
      `${API_URL}/ask`,
      { question: userMessage },
      { timeout: 30000 }
    );

    const analysis = response.data.analysis;

    // Split long messages
    const chunks = splitMessage(analysis, 3000);

    for (const chunk of chunks) {
      await message.reply(chunk);
      console.log(`📤 Sent: ${chunk.length} chars`);
    }

    await message.react('✅');
    console.log('✅ Complete\n');

  } catch (error) {
    console.error(`❌ Error: ${error.message}`);
    try {
      await message.reply('❌ Sorry, I encountered an error. Please try again.');
      await message.react('❌');
    } catch (replyError) {
      console.error('Could not send error message');
    }
  }
});

// ──────────────────────────────────────────────────────────────────────────
// Connection Lost
// ──────────────────────────────────────────────────────────────────────────

client.on('disconnected', (reason) => {
  console.log(`\n⚠️  Bot disconnected: ${reason}`);
  console.log('🔄 Attempting to reconnect...\n');
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

process.on('SIGTERM', async () => {
  console.log('\n\n👋 Shutting down bot...');
  await client.destroy();
  process.exit(0);
});