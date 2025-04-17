// AmazonSNS.js
const AWS = require('aws-sdk');
require('dotenv').config();

// Configure AWS credentials and region
AWS.config.update({
  region: process.env.AWS_REGION,
  accessKeyId: process.env.AWS_ACCESS_KEY_ID,
  secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY,
});

// Create SNS service object
const sns = new AWS.SNS({ apiVersion: '2010-03-31' });

// Send SMS function
function sendSMS(phoneNumber, message) {
  const params = {
    PhoneNumber: phoneNumber, // Format: +1234567890
    Message: message,
  };

  return sns
    .publish(params)
    .promise()
    .then((data) => {
      console.log('SNS MessageID:', data.MessageId);
      return { success: true, messageId: data.MessageId };
    })
    .catch((err) => {
      console.error('SNS Error:', err);
      return { success: false, error: err.message };
    });
}

module.exports = { sendSMS };
