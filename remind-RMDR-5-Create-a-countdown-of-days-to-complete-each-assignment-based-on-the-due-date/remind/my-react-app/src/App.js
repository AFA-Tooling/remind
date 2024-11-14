import React, { useState, useEffect } from 'react';
import './App.css';

function App() {
  const [phoneNumber, setPhoneNumber] = useState('');
  const [email, setEmail] = useState('');
  const [assignments, setAssignments] = useState([]);

  // Fetch assignments data
  useEffect(() => {
    fetch('http://localhost:3000/assignments')
      .then((response) => response.json())
      .then((data) => setAssignments(data))
      .catch((error) => console.error('Error fetching assignments:', error));
  }, []);

  // Handle sending SMS
  const handleSendSMS = (e) => {
    e.preventDefault();

    fetch('http://localhost:3000/send-sms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phoneNumber }),
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          alert('SMS sent successfully!');
          setPhoneNumber('');
        } else {
          alert('Failed to send SMS: ' + data.error);
        }
      })
      .catch((error) => {
        console.error('Error sending SMS:', error);
        alert('Failed to send SMS.');
      });
  };

  // Handle sending Email

  // const handleSendEmail = (e) => {
  //   e.preventDefault();
  
  //   if (email === "oindree@berkeley.edu") {
  //     fetch('http://localhost:5000/send-email', { // Update with correct endpoint
  //       method: 'POST',
  //       headers: {
  //         'Content-Type': 'application/json',
  //       },
  //       body: JSON.stringify({ email }),
  //     })
  //       .then((response) => {
  //         if (response.ok) {
  //           alert('Automated email sent successfully');
  //         } else {
  //           alert('Failed to send email');
  //         }
  //       })
  //       .catch((error) => {
  //         console.error('Error:', error);
  //         alert('An error occurred');
  //       });
  //   } else {
  //     alert('This feature only sends an automated email to "oindree@berkeley.edu".');
  //   }
  // };
  // eslint-disable-next-line
  const handleSendEmail = (e) => {
    e.preventDefault();
    

    

    fetch('http://localhost:3000/send-email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          alert('Email sent successfully!');
          setEmail('');
          handleSubmit(e);
        } else {
          alert('Failed to send email: ' + data.error);
        }
      })
      .catch((error) => {
        console.error('Error sending email:', error);
        alert('Failed to send email.');
      });
      
  };

  //handling if the email was correctly added 

  async function handleSubmit(event) {
    event.preventDefault();
    try {
      const response = await fetch('/save-email', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email }),
      });
  
      if (response.ok) {
        // Email saved successfully, you can clear the input or show a success message
        console.log('Email saved successfully');
      } else {
        const { error } = await response.json();
        console.error('Error saving email:', error);
      }
    } catch (error) {
      console.error('Error saving email:', error);
    }

     // Check if the email is valid
     if (email && !emailList.includes(email)) {
      setEmailList([...emailList, email]);
      setEmail('');
    }
  }

  // handling email list 

  const [emailList, setEmailList] = useState([]);

  // Handle form submission to add email to the list
  const handleSubmitt = (e) => {
    e.preventDefault();
    // Check if the email is valid
    if (email && !emailList.includes(email)) {
      setEmailList([...emailList, email]);
      setEmail('');
    }
  };



  // Render assignments with countdown
  const renderAssignments = () => {
    const today = new Date().getTime();
    const msInDay = 24 * 60 * 60 * 1000;

    return assignments.map((assignment) => {
      const daysUntilDue = Math.floor((assignment.dueDate - today) / msInDay);

      let message;
      if (daysUntilDue <= 3 && daysUntilDue >= 0) {
        message = `${assignment.title} is due in ${daysUntilDue} day(s)!`;
      } else if (daysUntilDue < 0) {
        message = `${assignment.title} was due ${Math.abs(daysUntilDue)} day(s) ago.`;
      } else {
        message = `${assignment.title} is due in ${daysUntilDue} day(s).`;
      }

      return (
        <li key={assignment.title} style={{ color: daysUntilDue < 0 ? 'red' : 'black' }}>
          {message}
          <br />
          <small>
            Assigned: {new Date(assignment.assignedDate).toLocaleDateString()} | Due: {new Date(assignment.dueDate).toLocaleDateString()}
          </small>
        </li>
      );
    });
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>AutoRemind Student-Facing Portal</h1>

        <section>
          <h2>Send Automated SMS</h2>
          <form onSubmit={handleSendSMS}>
            <label>
              Phone Number:
              <input
                type="tel"
                value={phoneNumber}
                onChange={(e) => setPhoneNumber(e.target.value)}
                placeholder="e.g., +1234567890"
                required
              />
            </label>
            <button type="submit">Send SMS</button>
          </form>
        </section>

        <section>
          <h2>Send Automated Email</h2>
          <form onSubmit={handleSubmit}>
            <label>
              Email Address:
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="e.g., student@example.com"
                required
              />
            </label>
            <button type="submit">Send Email</button>
          </form>
          <div> 
          <h2>Stored Emails:</h2>
          <ul>
            {emailList.map((email, index) => (
              <li key={index}>{email}</li>
            ))}
          </ul>
          </div>
        </section>

        {/* <section>
          <h2>Submit your email</h2>
          <form onSubmit={handleSubmitt}>
            <input
              type="email"
              value={email}
              placeholder="Enter your email"
              required
              />
              <button type="submit">Submit</button>
            </form>
          <div>
          <h2>Stored Emails:</h2>
          <ul>
            {emailList.map((email, index) => (
              <li key={index}>{email}</li>
            ))}
          </ul>
          </div>

        </section> */}
        <section/> 


        <section>
          <h2>Send Automated Discord Messages</h2>
          <label>Discord:</label>
          <a
            href="https://discord.com/login?redirect_to=%2Foauth2%2Fauthorize%3Fclient_id%3D1300523286274244639%26permissions%3D2048%26integration_type%3D0%26scope%3Dbot"
            rel="noopener noreferrer"
            target="_blank"
          >
            <button type="button">Connect to Server</button>
          </a>
        </section>

        <section>
          <h2>Assignment Countdown</h2>
          <ul>{renderAssignments()}</ul>
        </section>
      </header>
    </div>
  );
}

export default App;