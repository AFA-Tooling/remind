// function getAssignments() {
//     const assignments = [
//         { title: 'Project 1', assignedDate: '2024-09-03', dueDate: '2024-09-10' },
//         { title: 'Project 2', assignedDate: '2024-09-15', dueDate: '2024-09-26' },
//         { title: 'Lab 2', assignedDate: '2024-09-04', dueDate: '2024-09-08' },
//         { title: 'Lab 3', assignedDate: '2024-09-09', dueDate: '2024-09-14' },
//         { title: 'Lab 4', assignedDate: '2024-09-11', dueDate: '2024-09-18' }
//     ];

//     assignments.forEach(assignment => {
//         assignment.assignedDate = new Date(assignment.assignedDate).getTime();
//         assignment.dueDate = new Date(assignment.dueDate).getTime();
//     });

//     return assignments;
// }

// function countdownAssignments(assignments) {
//     const today = new Date().getTime();
//     const msInDay = 24 * 60 * 60 * 1000; 

//     assignments.forEach(assignment => {
//         const daysUntilDue = Math.floor((assignment.dueDate - today) / msInDay);

//         if (daysUntilDue <= 3 && daysUntilDue >= 0) {
//             console.log(`${assignment.title} is due in ${daysUntilDue} day(s)!`);
//         } else if (daysUntilDue < 0) {
//             console.log(`${assignment.title} was due ${Math.abs(daysUntilDue)} day(s) ago.`);
//         }
//     });
// }

// const myAssignments = getAssignments();
// countdownAssignments(myAssignments);

// backend.js

require('dotenv').config();
const express = require('express');
const cors = require('cors');
const bodyParser = require('body-parser');
const nodemailer = require('nodemailer');

// Twilio configuration
const accountSid = process.env.TWILIO_ACCOUNT_SID;
const authToken = process.env.TWILIO_AUTH_TOKEN;
const twilioPhoneNumber = process.env.TWILIO_PHONE_NUMBER;
const client = require('twilio')(accountSid, authToken);

const app = express();
app.use(cors());
app.use(bodyParser.json());

// Endpoint to send SMS message
app.post('/send-sms', (req, res) => {
  const { phoneNumber } = req.body;

  // Validate phone number
  if (!phoneNumber || !/^\+?[1-9]\d{1,14}$/.test(phoneNumber)) {
    return res.status(400).json({ error: 'Invalid phone number' });
  }

  const message = 'This is your automated message.';

  client.messages
    .create({
      body: message,
      from: twilioPhoneNumber,
      to: phoneNumber,
    })
    .then((message) => {
      console.log('SMS sent:', message.sid);
      res.json({ success: true });
    })
    .catch((error) => {
      console.error('Error sending SMS:', error);
      res.status(500).json({ error: 'Failed to send SMS' });
    });
});

// Endpoint to send email
app.post('/send-email', (req, res) => {
  const { email } = req.body;

  // Validate email
  if (!email || !/^\S+@\S+\.\S+$/.test(email)) {
    return res.status(400).json({ error: 'Invalid email address' });
  }

  // Configure nodemailer transporter
  const transporter = nodemailer.createTransport({
    service: 'Gmail', // or another email service
    auth: {
      user: process.env.EMAIL_USERNAME,
      pass: process.env.EMAIL_PASSWORD,
    },
  });

  const mailOptions = {
    from: process.env.EMAIL_USERNAME,
    to: email,
    subject: 'Automated Message',
    text: 'This is your automated message.',
  };

  transporter.sendMail(mailOptions, (error, info) => {
    if (error) {
      console.error('Error sending email:', error);
      res.status(500).json({ error: 'Failed to send email' });
    } else {
      console.log('Email sent:', info.response);
      res.json({ success: true });
    }
  });
});

// Endpoint to get assignments data
app.get('/assignments', (req, res) => {
  const assignments = [
    { title: 'Project 1', assignedDate: '2024-10-06', dueDate: '2024-10-12' },
    { title: 'Project 2', assignedDate: '2024-10-10', dueDate: '2024-10-20' },
    { title: 'Lab 2', assignedDate: '2024-10-05', dueDate: '2024-10-08' },
    { title: 'Lab 3', assignedDate: '2024-10-07', dueDate: '2024-10-09' },
    { title: 'Lab 4', assignedDate: '2024-10-08', dueDate: '2024-10-11' },
  ];

  // Convert assignedDate and dueDate to timestamps
  assignments.forEach((assignment) => {
    assignment.assignedDate = new Date(assignment.assignedDate).getTime();
    assignment.dueDate = new Date(assignment.dueDate).getTime();
  });

  res.json(assignments);
});

app.listen(5000, () => {
  console.log('Backend server is running on port 5000');
});
