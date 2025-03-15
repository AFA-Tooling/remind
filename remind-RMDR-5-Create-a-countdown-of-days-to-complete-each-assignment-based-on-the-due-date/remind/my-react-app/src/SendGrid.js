require('dotenv').config();
const sendGrid = require("@sendgrid/mail")
const fs = require('fs');
const path = require('path');
const SENDGRID_API_KEY = process.env.SENDGRID_API_KEY;
sendGrid.setApiKey(SENDGRID_API_KEY)

async function sendEmail() {
    const messageData = {
        to:['autoremindberkeley@gmail.com', 'oindree@berkeley.edu', 'ankitasun@berkeley.edu'],
        from:'autoremindberkeley@gmail.com',
        subject:'Email template test',
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

async function sendEmail2(studentData) {
    const templatePath = path.join(__dirname, 'emailtemplate.html');
    let emailTemplate = fs.readFileSync(templatePath, 'utf8');

    if (studentData && studentData.name) {
        emailTemplate = emailTemplate.replace('{{name}}', studentData.name);
    }

    const messageData = {
        to:['autoremindberkeley@gmail.com', 'oindree@berkeley.edu', 'ankitasun@berkeley.edu'],
        from:'autoremindberkeley@gmail.com',
        subject:'[Action Required] - CS 10 Incomplete Form',
        text:'this is a test',
        html: emailTemplate,
    };
    try {
        await sendGrid.send(messageData);
        console.log('Email sent successfully');
    } catch (error) {
        console.log(error);
    }
}

//sendEmail();
sendEmail2({name: 'Student Name'});