require('dotenv').config();
const sendGrid = require('@sendgrid/mail');

const SENDGRID_API_KEY = process.env.SENDGRID_API_KEY;
sendGrid.setApiKey(SENDGRID_API_KEY);

const carrierGateways = {
    att: '@txt.att.net',
    verizon: '@vtext.com',
    tmobile: '@tmomail.net',
    sprint: '@messaging.sprintpcs.com',
    boost: '@myboostmobile.com',
};

async function sendTextMessage(phoneNumber, carrier, message) {
    const domain = carrierGateways[carrier.toLowerCase()];
    if (!domain) {
        console.error('Unsupported carrier:', carrier);
        return { success: false, error: 'Unsupported carrier' };
    }

    const smsEmail = `${phoneNumber}${domain}`;

    const messageData = {
        to: smsEmail,
        from: 'autoremindberkeley@gmail.com', // Same verified sender
        subject: '',  // Leave subject empty for SMS
        text: message,
    };

    try {
        await sendGrid.send(messageData);
        console.log(`Text message sent successfully to ${smsEmail}`);
        return { success: true };
    } catch (error) {
        console.error('Error sending text message:', error);
        return { success: false, error: error.message };
    }
}

module.exports = { sendTextMessage };
