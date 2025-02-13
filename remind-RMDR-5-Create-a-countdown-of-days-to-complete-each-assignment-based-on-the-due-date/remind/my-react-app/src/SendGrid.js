require('dotenv').config();
const sendGrid = require("@sendgrid/mail")
const SENDGRID_API_KEY = process.env.SENDGRID_API_KEY;
sendGrid.setApiKey(SENDGRID_API_KEY)

async function sendEmail() {
    const messageData = {
        to:'autoremindberkeley@gmail.com',
        from:'autoremindberkeley@gmail.com',
        subject:'Test email',
        text:'this is a test',
        html:'<p>this is a test</p>',
    };
    try {
        await sendGrid.send(messageData);
        console.log('Email sent successfully');
    } catch (error) {
        console.log(error);
    }
}
sendEmail();