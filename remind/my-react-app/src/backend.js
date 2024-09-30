/*function studentList() {
    const students = [
        { name: 'John Doe', assignment: 'HW 1', assignmentDate: new Date},
        { name: 'Jane Smith', assignment: 'Lab 1', assignmentDate: new Date},
        { name: 'Bob Johnson', assignment: 'Project 1', assignmentDate: new Date}
    ];

    return students.map((student) => {
        return (
            <div key={student.name}>
                <h2>{student.name}</h2>
                <p>Assignment: {student.assignment}</p>
                <p>Assignment Date: {student.assignmentDate}</p>
            </div>
        );
    });
}*/

function getAssignments() {
    const assignments = [
        { title: 'Project 1', assignedDate: '2024-09-03', dueDate: '2024-09-10' },
        { title: 'Project 2', assignedDate: '2024-09-15', dueDate: '2024-09-26' },
        { title: 'Lab 2', assignedDate: '2024-09-04', dueDate: '2024-09-08' },
        { title: 'Lab 3', assignedDate: '2024-09-09', dueDate: '2024-09-14' },
        { title: 'Lab 4', assignedDate: '2024-09-11', dueDate: '2024-09-18' }
    ];

    assignments.forEach(assignment => {
        assignment.assignedDate = new Date(assignment.assignedDate).getTime();
        assignment.dueDate = new Date(assignment.dueDate).getTime();
    });

    return assignments;
}

function countdownAssignments(assignments) {
    const today = new Date().getTime();
    const msInDay = 24 * 60 * 60 * 1000; 

    assignments.forEach(assignment => {
        const daysUntilDue = Math.floor((assignment.dueDate - today) / msInDay);

        if (daysUntilDue <= 3 && daysUntilDue >= 0) {
            console.log(`${assignment.title} is due in ${daysUntilDue} day(s)!`);
        } else if (daysUntilDue < 0) {
            console.log(`${assignment.title} was due ${Math.abs(daysUntilDue)} day(s) ago.`);
        }
    });
}

const myAssignments = getAssignments();
countdownAssignments(myAssignments);
