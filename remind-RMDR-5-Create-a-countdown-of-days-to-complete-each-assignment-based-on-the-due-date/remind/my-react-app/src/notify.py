from flask import Flask, jsonify, request

app = Flask(__name__)

# Home route
@app.route('/')
def home():
    return jsonify({'message': 'Server is running!'})

# Example POST route
@app.route('/api', methods=['POST'])
def example_api():
    data = request.json  # Get JSON data from request
    return jsonify({'received': data}), 200

if __name__ == '__main__':
    app.run(port=5000, debug=True)
