import React, { useState, useEffect } from 'react';
import './App.css';

function App() {
  const [phoneNumber, setPhoneNumber] = useState('');
  const [email, setEmail] = useState('');
  const [assignments, setAssignments] = useState([]);
  const [frequency, setFrequency] = useState('');
  const [scrapedData, setScrapedData] = useState({
    assignments : [],
    officeHours: [],
    resources: [],
  })

  // Fetch assignments data
  useEffect(() => {
    fetch('http://localhost:3000/assignments')
      .then((response) => response.json())
      .then((data) => setAssignments(data))
      .catch((error) => console.error('Error fetching assignments:', error));
  }, []);

  // Fetch scraped course data
  useEffect(() => {
    fetch('http://localhost:3000/scrape-course')
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          setScrapedData(data.data); // store scraped data in state
        } else {
          console.error('Error fetching scraped data:', data.error);
        }
      })
      .catch((error) => console.error('Fetch error:', error));
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

  // Allow the user to customize the notification frequency
  const handleSetFrequency = (e) => {
    e.preventDefault();
    fetch('http://localhost:3000/set-frequency', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ frequency }),
    })
     .then((response) => response.json())
     .then((data) => {
      if (data.success) {
        alert('Notification frequency updated successfully!');
        setFrequency('');
      } else {
        alert('Failed to update notification frequency: ' + data.error);
      }
     })
     .catch((error) => {
       console.error('Error updating frequency:', error);
       alert('An error occured.');
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



  /*// Render assignments with countdown
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
  };*/

  // Render scraped assignments
  const renderScrapedAssignments = () => {
    return scrapedData.assignments.map((assignment, index) => (
      <li key={index}>
        {assignment.title} - Due: {assignment.dueDate}
      </li>
    ));
  };

  const renderOfficeHours = () => {
    return scrapedData.officeHours.map((oh, index) => <li key={index}>{oh}</li>);
  };

  const renderResources = () => {
    return scrapedData.resources.map((resource, index) => (
      <li key={index}>
        <a href={resource.url} target="_blank" rel="noopener noreferrer">
          {resource.name}
        </a>
      </li>
    ));
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

        <section>
          <h2>Set Notification Frequency</h2>
          <form onSubmit={handleSetFrequency}>
            <label>
              Frequency (days):
              <input
                type="number"
                min="1"
                value={frequency}
                onChange={(e) => setFrequency(e.target.value)}
                placeholder="Enter frequency in days"
                required
              />
            </label>
            <button type="submit">Set Frequency</button>
          </form>
        </section>
      </header>
    </div>
  );
}

export default App;