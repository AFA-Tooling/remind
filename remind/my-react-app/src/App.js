// import logo from './logo.svg';
// import './App.css';
// import React, { useEffect, useState } from 'react';
// // import logo from './logo'; // Adjust the import based on your project structure
// // import './App.css'; // Adjust the import based on your project structure

// function App() {
//   const [data, setData] = useState(null);

//   useEffect(() => {
//     fetch('https://your-backend-endpoint.com/api/data') // Replace with your backend endpoint
//       .then(response => response.json())
//       .then(data => setData(data))
//       .catch(error => console.error('Error fetching data:', error));
//   }, []);

//   return (
//     <div className="App">
//       <header className="App-header">
//         <img src={logo} className="App-logo" alt="logo" />
//         <p>
//           Edit <code>src/App.js</code> and save to reload.
//         </p>
//         <a
//           className="App-link"
//           href="https://reactjs.org"
//           target="_blank"
//           rel="noopener noreferrer"
//         >
//           Learn React
//         </a>
//         {data ? (
//           <div>
//             <h2>Data from Backend:</h2>
//             <pre>{JSON.stringify(data, null, 2)}</pre>
//           </div>
//         ) : (
//           <p>Loading data...</p>
//         )}
//       </header>
//     </div>
//   );
// }

// export default App;

// // function App() {
// //   return (
// //     <div className="App">
// //       <header className="App-header">
// //         <img src={logo} className="App-logo" alt="logo" />
// //         <p>
// //           Edit <code>src/App.js</code> and save to reload.
// //         </p>
// //         <a
// //           className="App-link"
// //           href="https://reactjs.org"
// //           target="_blank"
// //           rel="noopener noreferrer"
// //         >
// //           Learn React
// //         </a>
// //       </header>
// //     </div>
// //   );
// // }

// // export default App;

// app.js

import React, { useState, useEffect } from 'react';
import './App.css';

function App() {
  const [phoneNumber, setPhoneNumber] = useState('');
  const [email, setEmail] = useState('');
  const [assignments, setAssignments] = useState([]);

  // Fetch assignments data
  useEffect(() => {
    fetch('http://localhost:5000/assignments')
      .then((response) => response.json())
      .then((data) => setAssignments(data))
      .catch((error) => console.error('Error fetching assignments:', error));
  }, []);

  // Handle sending SMS
  const handleSendSMS = (e) => {
    e.preventDefault();

    fetch('http://localhost:5000/send-sms', {
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
  const handleSendEmail = (e) => {
    e.preventDefault();

    fetch('http://localhost:5000/send-email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          alert('Email sent successfully!');
          setEmail('');
        } else {
          alert('Failed to send email: ' + data.error);
        }
      })
      .catch((error) => {
        console.error('Error sending email:', error);
        alert('Failed to send email.');
      });
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
            Assigned: {new Date(assignment.assignedDate).toLocaleDateString()} | Due:{' '}
            {new Date(assignment.dueDate).toLocaleDateString()}
          </small>
        </li>
      );
    });
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>Student Communication Portal</h1>

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
          <form onSubmit={handleSendEmail}>
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
