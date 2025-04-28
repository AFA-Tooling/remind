require('dotenv').config();
const sendGrid = require("@sendgrid/mail")
const fs = require('fs');
const path = require('path');
const csv = require('csv-parse/sync');
const SENDGRID_API_KEY = process.env.SENDGRID_API_KEY;
sendGrid.setApiKey(SENDGRID_API_KEY)

// Function to read message requests from CSV
function readMessageRequests(filePath) {
    try {
        const fileContent = fs.readFileSync(filePath, 'utf-8');
        const records = csv.parse(fileContent, {
            columns: true,
            skip_empty_lines: true
        });
        return records;
    } catch (error) {
        console.error('Error reading message requests:', error);
        return [];
    }
}

// Function to send email using message request data
async function sendMessageRequestEmail(messageRequest) {
    const messageData = {
        to: messageRequest.email,
        from: 'autoremindberkeley@gmail.com',
        subject: `[Action Required] - ${messageRequest.assignment}`,
        text: messageRequest.message_requests,
        html: `<p>${messageRequest.message_requests}</p>`,
    };

    try {
        await sendGrid.send(messageData);
        console.log(`Email sent successfully to ${messageRequest.email}`);
        return true;
    } catch (error) {
        console.error(`Error sending email to ${messageRequest.email}:`, error);
        return false;
    }
}

// Function to process all message requests from a file
async function processMessageRequests(filePath) {
    const messageRequests = readMessageRequests(filePath);
    const results = {
        successful: 0,
        failed: 0,
        total: messageRequests.length
    };

    for (const request of messageRequests) {
        const success = await sendMessageRequestEmail(request);
        if (success) {
            results.successful++;
        } else {
            results.failed++;
        }
    }

    console.log('Email sending results:', results);
    return results;
}

// Test function to send a single test email
async function sendTestEmail() {
    const testMessageRequest = {
        email: 'autoremindberkeley@gmail.com',
        assignment: 'Test Assignment',
        message_requests: 'This is a test email to verify the SendGrid integration is working correctly.'
    };

    return await sendMessageRequestEmail(testMessageRequest);
}

// Example usage:
// To test with a single email:
// sendTestEmail();

// To process all message requests from a file:
// processMessageRequests('path/to/your/message_requests.csv');

module.exports = {
    sendTestEmail,
    processMessageRequests,
    sendMessageRequestEmail
};