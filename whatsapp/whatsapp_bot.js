// whatsapp/whatsapp_bot.js - COMPLETE DEBUG VERSION
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
require('dotenv').config();

// ⚙️ CONFIGURATION - Load ONLY from .env (NO DEFAULTS FOR SECRETS)
const MAIN_NUMBER = process.env.WHATSAPP_MAIN_NUMBER;
const WHATSAPP_LID = process.env.WHATSAPP_LID;
const WHATSAPP_PIN = process.env.WHATSAPP_PIN;
const API_URL = process.env.WHATSAPP_API_URL || 'http://localhost:8000';
const API_PORT = process.env.WHATSAPP_API_PORT || 8000;

// Validate required .env variables
if (!MAIN_NUMBER || !WHATSAPP_LID || !WHATSAPP_PIN) {
  console.error('\n❌ ERROR: Missing required .env variables:');
  if (!MAIN_NUMBER) console.error('  - WHATSAPP_MAIN_NUMBER');
  if (!WHATSAPP_LID) console.error('  - WHATSAPP_LID');
  if (!WHATSAPP_PIN) console.error('  - WHATSAPP_PIN');
  console.error('\nUpdate your .env file and try again.\n');
  process.exit(1);
}

console.log('\n═══════════════════════════════════════════════════════');
console.log('🤖 PesaPilot WhatsApp Bot');
console.log('═══════════════════════════════════════════════════════');
console.log(`📱 Phone Number : ✓ configured`);
console.log(`🔑 LID          : ✓ configured`);
console.log(`🔐 PIN          : ✓ configured`);
console.log(`🔗 API URL      : ${API_URL}`);
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
  console.log('║              ✅ BOT IS ONLINE!                        ║');
  console.log('╚═══════════════════════════════════════════════════════╝');
  console.log(`🤖 Bot WhatsApp ID : ${client.info.wid._serialized}`);
  console.log(`📞 Authorized      : phone number & LID configured`);
  console.log(`🔗 API             : ${API_URL}`);
  console.log('\n💡 Send a message from your main Safaricom number\n');
  console.log('💬 Examples:');
  console.log('  • "What did I spend on food?"');
  console.log('  • "How much did I send to Safaricom?"');
  console.log('  • "Summary"');
  console.log('  • "Help"\n');
  console.log(`📝 Manual entry: PIN|PASTE_SMS_HERE\n`);
});

// ──────────────────────────────────────────────────────────────────────────
// Incoming Messages - DEBUG VERSION
// ──────────────────────────────────────────────────────────────────────────

client.on('message', async (message) => {
  try {
    const senderNumber = message.from;
    const userMessage = message.body.trim();

    console.log(`\n📨 Raw message: "${userMessage}"`);
    console.log(`📨 Message length: ${userMessage.length}`);
    console.log(`📨 First 10 chars: "${userMessage.substring(0, 10)}"`);
    console.log(`📨 PIN env: "${WHATSAPP_PIN}"`);
    console.log(`📨 PIN + |: "${WHATSAPP_PIN}|"`);

    // Check if starts with PIN
    const startsWithPin = userMessage.startsWith(WHATSAPP_PIN + '|');
    console.log(`📨 Starts with PIN|: ${startsWithPin}`);

    // Strip @c.us / @lid suffix for clean comparison
    const senderNumeric = senderNumber.replace(/@.*$/, '');
    const mainNumeric = MAIN_NUMBER.replace(/@.*$/, '');
    const lidNumeric = WHATSAPP_LID.replace(/@.*$/, '');

    console.log(`📱 From: ${senderNumeric}`);

    // Authorize if sender matches EITHER phone number OR LID
    let isAuthorized = false;
    let matchedBy = '';

    if (mainNumeric && senderNumeric === mainNumeric) {
      isAuthorized = true;
      matchedBy = 'phone number';
    } else if (lidNumeric && senderNumeric === lidNumeric) {
      isAuthorized = true;
      matchedBy = 'LID';
    }

    // Fallback — try contact info
    if (!isAuthorized) {
      try {
        const contact = await message.getContact();
        const contactNum = (contact.number || '').replace(/@.*$/, '');
        console.log(`👤 Contact: ${contact.name || 'Unknown'}`);

        if ((mainNumeric && contactNum === mainNumeric) || (lidNumeric && contactNum === lidNumeric)) {
          isAuthorized = true;
          matchedBy = 'contact lookup';
        }
      } catch (e) {
        console.log('⚠️  Could not get contact info');
      }
    }

    if (!isAuthorized) {
      console.log(`❌ Unauthorized`);
      await message.reply('⛔ This number is not authorized.');
      await message.react('🚫');
      return;
    }

    console.log(`✅ Authorized via ${matchedBy}`);
    await message.react('⏳');

    // ─ MANUAL SMS ENTRY ─────────────────────────────────────────────────────
    if (userMessage.startsWith(WHATSAPP_PIN + '|')) {
      console.log('📝 ✅ MANUAL SMS ENTRY DETECTED');

      const smsContent = userMessage.substring(WHATSAPP_PIN.length + 1).trim();

      console.log(`📝 SMS Content: "${smsContent.substring(0, 50)}..."`);
      console.log(`📝 SMS Length: ${smsContent.length}`);

      if (!smsContent) {
        console.log('❌ SMS content is empty');
        await message.reply('❌ Empty SMS.\n\nFormat: PIN|SMS_CONTENT');
        await message.react('❌');
        return;
      }

      console.log(`🔄 Sending to API for parsing...`);

      try {
        const response = await axios.post(
          `${API_URL}/parse-sms`,
          { sms_content: smsContent },
          { timeout: 20000 }
        );

        console.log(`📡 API Response:`, response.data);

        if (response.data.success) {
          console.log('✅ Success! SMS parsed and stored');
          await message.reply(`${response.data.summary}`);
          await message.react('✅');
          console.log('✅ SMS parsed and stored\n');
        } else {
          console.log(`❌ API returned error: ${response.data.error}`);
          await message.reply(`❌ ${response.data.error}`);
          await message.react('❌');
          console.log(`⚠️ Parse failed: ${response.data.error}\n`);
        }
      } catch (error) {
        console.error(`❌ API Error: ${error.message}`);
        console.error(`❌ Full error:`, error.response?.data || error);
        await message.reply('❌ Error processing SMS. Try again.');
        await message.react('❌');
      }
      return;
    }

    // ─ REGULAR QUESTIONS ────────────────────────────────────────────────────
    console.log('🔄 Processing question (not SMS)...');

    try {
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
      console.log('✅ Done\n');
    } catch (error) {
      console.error(`❌ Error: ${error.message}`);
      await message.reply('❌ Sorry, something went wrong. Please try again.');
      await message.react('❌');
    }
  } catch (error) {
    console.error(`❌ Error: ${error.message}`);
    try {
      await message.reply('❌ Something went wrong.');
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
  console.log(`\n⚠️  Disconnected: ${reason}`);
  console.log('🔄 Attempting to reconnect...\n');
});

// ──────────────────────────────────────────────────────────────────────────
// Helper — split long messages
// ──────────────────────────────────────────────────────────────────────────

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

// ──────────────────────────────────────────────────────────────────────────
// Start
// ──────────────────────────────────────────────────────────────────────────

client.initialize();

process.on('SIGINT', async () => {
  console.log('\n\n👋 Shutting down...');
  await client.destroy();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  console.log('\n\n👋 Shutting down...');
  await client.destroy();
  process.exit(0);
});