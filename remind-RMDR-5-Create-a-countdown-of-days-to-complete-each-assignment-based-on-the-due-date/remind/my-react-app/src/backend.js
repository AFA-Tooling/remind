const express = require('express');
const cors = require('cors');
require('dotenv').config();
const sgMail = require('@sendgrid/mail');
const twilio = require('twilio');
const fs = require('fs'); // Import the file system module
const frequencyFilePath = 'frequency.txt';
// webscraping
const axios = require('axios');
const cheerio = require('cheerio');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());
sgMail.setApiKey(process.env.SENDGRID_API_KEY);

// Twilio configuration
const accountSid = process.env.TWILIO_ACCOUNT_SID;
const authToken = process.env.TWILIO_AUTH_TOKEN;
const client = twilio(accountSid, authToken);
const twilioPhoneNumber = process.env.TWILIO_PHONE_NUMBER;

// Ensure emails.txt exists, create it if not
const emailsFilePath = 'emails.txt';
if (!fs.existsSync(emailsFilePath)) {
  fs.writeFileSync(emailsFilePath, '', (err) => {
    if (err) console.error('Error creating emails.txt:', err);
  });
  console.log('emails.txt created successfully');
}

// Endpoint to send SMS message
app.post('/send-sms', (req, res) => {
  const { phoneNumber } = req.body;

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

// Endpoint to send email with SendGrid

  app.post('/send-email', (req, res) => {
    const { email } = req.body;
  
    const msg = {
      to: email,
      from: 'oindree@berkeley.edu',
      subject: 'Sending with SendGrid is Fun',
      text: 'and easy to do anywhere, even with Node.js',
      html: '<strong>and easy to do anywhere, even with Node.js</strong>',
    };
  
    sgMail
      .send(msg)
      .then(() => {
        console.log('Email sent');
        res.status(200).send('Email sent successfully');
      })
      .catch((error) => {
        console.error('Error sending email:', error);
        res.status(500).send('Error sending email');
      });
  });


// Array to hold emails in memory and save them to a file
const emails = [];

// Endpoint to save email and log it to a file
app.post('/save-email', (req, res) => {
  const { email } = req.body;
  if (!email || !validateEmail(email)) {
    return res.status(400).json({ error: 'Invalid email address' });
  }

  emails.push(email);
  console.log('Stored email:', email);

  // Append the email to emails.txt file
  fs.appendFile(emailsFilePath, email + '\n', (err) => {
    if (err) {
      console.error('Error writing email to file:', err);
      return res.status(500).json({ error: 'Failed to save email to file' });
    }
    res.status(200).json({ message: 'Email saved successfully' });
  });
});

// Endpoint to log emails to console
app.get('/list-emails', (req, res) => {
  console.log("Current email list:", emails);
  res.status(200).send('Check server console for email list.');
});

// Endpoint to get emails (if needed in secure context)
app.get('/get-emails', (req, res) => {
  res.status(200).json(emails);
});

// Function to validate email format
function validateEmail(email) {
  return /^\w+([\.-]?\w+)*@\w+([\.-]?\w+)*(\.\w{2,3})+$/.test(email);
}

// Endpoint to get assignments data
app.get('/assignments', (req, res) => {
  const assignments = [
    { title: 'Project 1', assignedDate: '2024-10-06', dueDate: '2024-10-12' },
    { title: 'Project 2', assignedDate: '2024-10-10', dueDate: '2024-10-20' },
    { title: 'Lab 2', assignedDate: '2024-10-05', dueDate: '2024-10-08' },
    { title: 'Lab 3', assignedDate: '2024-10-07', dueDate: '2024-10-09' },
    { title: 'Lab 4', assignedDate: '2024-10-08', dueDate: '2024-10-11' },
  ];

  assignments.forEach((assignment) => {
    assignment.assignedDate = new Date(assignment.assignedDate).getTime();
    assignment.dueDate = new Date(assignment.dueDate).getTime();
  });

  res.json(assignments);
});

// Ensure frequency.txt exists, create it if not
if (!fs.existsSync(frequencyFilePath)) {
  fs.writeFileSync(frequencyFilePath, '', (err) => {
    if (err) console.error('Error creating frequency.txt:', err);
  });
  console.log('frequency.txt created successfully');
}

// Endpoint to set notification frequency
app.post('/set-frequency', (req, res) => {
  const { frequency } = req.body;

  // Validate frequency input
  if (!frequency || isNaN(frequency) || frequency <= 0) {
    return res.status(400).json({ success: false, error: 'Invalid frequency value' });
  }

  // Append frequency to the file
  const data = `Frequency: ${frequency} days\n`;
  fs.appendFile(frequencyFilePath, data, (err) => {
    if (err) {
      console.error('Error saving frequency to file:', err);
      return res.status(500).json({ success: false, error: 'Failed to save frequency to file' });
    }

    console.log('Frequency saved:', frequency);
    res.status(200).json({ success: true, message: 'Notification frequency saved successfully.' });
  });
});

// scrape course data (assignments, office hours, etc.)
async function ScrapeCourseData() {
  try {
    const url = "https://example.com/course-page"; // replace with the actual course URL
    const { data: html } = await axios.get(url); // fetch HTML from the website
    const $ = cheerio.load(html);

    // extract assignments
    const assignments = [];
    $("table.assignments-table tr").each((index, element) => {
      if (index == 0) return; // skip header row
      const title = $(element).find("td.title").text().trim();
      const dueDate = $(element).find("td.due-date").text().trim();
      assignments.push({ title, dueDate });
    })

    // extract office hours
    const officeHours = [];
    $("div.office-hours p").each((_, element) => {
      officeHours.push($(element).text().trim());
    });

    // extract resources
    const resources = [];
    $("div.resources a").each((_, element) => {
      const resourceName = $(element).text().trim();
      const resourceLink = $(element).attr("href");
      resources.push({ name: resourceName, url: resourceLink });
    });

    return { assignments, officeHours, resources };
  } catch (error) {
    console.error("Error scraping course data:", error);
    return { error: "Failed to scrape course data" };
  }
}

app.get('/scrape-course', async (req, res) => {
  const data = await ScrapeCourseData();
  if (data.error) {
    return res.status(500).json({ success: false, error: data.error });
  }
  res.status(200).json({ success: true, data });
})

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
