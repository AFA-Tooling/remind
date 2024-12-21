Automated reminders for students, powered by a single source of truth.

AutoRemind is a microservice designed to centralize communication with students about their coursework. By integrating with Learning Management Systems (LMS), starting with GradeView, AutoRemind delivers timely, automated messages containing critical course information and direct access to related resources.

Notable Features

1. Automated Messaging: Sends reminders via email or SMS about coursework deadlines, announcements, and updates.

2. Resource Links: Includes a curated list of resources for students to access directly from their messages.

3. LMS Integration: Seamlessly integrates with LMS platforms, beginning with GradeView.

4. Single Source of Truth: Ensures consistency and accuracy by pulling data from a unified backend.

5. API Calls: Utilizes Twilio for SMS notifications and SendGrid for email delivery.

Integration with LMS (GradeView)

AutoRemind will use the GradeView API to fetch and push course-related updates. The system ensures that students receive reminders tailored to their enrolled courses (CS 10 for now). Future updates will include expanded integration with other LMS platforms and courses.

