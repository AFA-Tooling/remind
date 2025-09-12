const { sendTestEmail, processMessageRequests } = require('./SendGrid');
const path = require('path');

// Function to run the test
async function runTest() {
    console.log('Starting SendGrid email test...');
    
    try {
        // Test 1: Send a single test email
        console.log('\nTest 1: Sending test email...');
        const testResult = await sendTestEmail();
        console.log('Test email result:', testResult ? 'Success' : 'Failed');

        // Test 2: Process message requests from a file
        console.log('\nTest 2: Processing message requests...');
        // Use absolute path to the message requests file
        const messageRequestsPath = path.join(__dirname, '../../../../email-service/message_requests/message_requests_Project 3: 2048.csv');
        console.log('Using message requests file:', messageRequestsPath);
        const messageRequestsResult = await processMessageRequests(messageRequestsPath);
        console.log('Message requests processing result:', messageRequestsResult);
    } catch (error) {
        console.error('Error during testing:', error);
    }
}

// Run the test
runTest(); 