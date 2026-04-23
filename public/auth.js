// auth.js - Firebase Authentication Module
class FirebaseAuth {
    constructor() {
        this.user = null;
        this.session = null;
        this.loading = true;
        this.error = null;
        this.listeners = [];
        this._auth = null;

        // Initialize Firebase app using server-injected credentials
        const apiKey = window.FIREBASE_API_KEY || '';
        const authDomain = window.FIREBASE_AUTH_DOMAIN || '';
        const projectId = window.FIREBASE_PROJECT_ID || '';

        if (!apiKey || !authDomain) {
            console.error('Missing Firebase credentials. Please set FIREBASE_API_KEY and FIREBASE_AUTH_DOMAIN.');
            this.loading = false;
            return;
        }

        if (typeof firebase === 'undefined') {
            console.error('Firebase library not loaded. Make sure the Firebase SDK is included before this script.');
            this.loading = false;
            return;
        }

        try {
            // Initialize app only once
            let app;
            if (!firebase.apps || !firebase.apps.length) {
                app = firebase.initializeApp({ apiKey, authDomain, projectId });
            } else {
                app = firebase.apps[0];
            }
            this._auth = firebase.auth(app);
            this.init();
        } catch (error) {
            console.error('Error initializing Firebase:', error);
            this.loading = false;
        }
    }

    async getToken() {
        if (!this.user) return null;
        return this.user.getIdToken();
    }

    init() {
        this._auth.onAuthStateChanged(async (user) => {
            this.user = user;
            this.session = user ? { user } : null;
            if (user) {
                try {
                    const token = await user.getIdToken();
                    await fetch('/api/reminders/register', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                        body: JSON.stringify({ display_name: user.displayName || '' }),
                    });
                } catch (e) {
                    console.warn('Could not register user in Firestore:', e);
                }
            }
            this.loading = false;
            this.notifyListeners();
        }, (error) => {
            console.error('Auth state error:', error);
            this.error = error;
            this.loading = false;
            this.notifyListeners();
        });
    }

    // Subscribe to auth state changes
    onAuthStateChange(callback) {
        this.listeners.push(callback);
        // Immediately call with current state
        callback(this.user, this.session, this.loading);
        return () => {
            this.listeners = this.listeners.filter(l => l !== callback);
        };
    }

    notifyListeners() {
        this.listeners.forEach(callback => {
            callback(this.user, this.session, this.loading);
        });
    }

    async signUp(email, password) {
        if (!this._auth) return { data: null, error: { message: 'Firebase not initialized' } };
        this.loading = true;
        this.error = null;
        try {
            const result = await this._auth.createUserWithEmailAndPassword(email, password);
            this.loading = false;
            this.notifyListeners();
            return { data: result, error: null };
        } catch (error) {
            console.error('Sign up error:', error);
            this.error = error;
            this.loading = false;
            this.notifyListeners();
            return { data: null, error };
        }
    }

    async signIn(email, password) {
        if (!this._auth) {
            return { data: null, error: { message: 'Firebase not initialized' } };
        }
        this.loading = true;
        this.error = null;
        try {
            const result = await this._auth.signInWithEmailAndPassword(email, password);
            this.loading = false;
            this.notifyListeners();
            return { data: result, error: null };
        } catch (error) {
            console.error('Sign in error:', error);
            this.error = error;
            this.loading = false;
            this.notifyListeners();
            return { data: null, error };
        }
    }

    async signOut() {
        if (!this._auth) return { error: { message: 'Firebase not initialized' } };
        this.loading = true;
        this.error = null;
        try {
            await this._auth.signOut();
            this.loading = false;
            this.notifyListeners();
            return { error: null };
        } catch (error) {
            console.error('Sign out error:', error);
            this.error = error;
            this.loading = false;
            this.notifyListeners();
            return { error };
        }
    }

    async signInWithGoogle() {
        if (!this._auth) {
            const error = { message: 'Firebase not initialized' };
            this.error = error;
            this.loading = false;
            this.notifyListeners();
            return { data: null, error };
        }
        this.loading = true;
        this.error = null;
        try {
            const provider = new firebase.auth.GoogleAuthProvider();
            const result = await this._auth.signInWithPopup(provider);
            this.loading = false;
            this.notifyListeners();
            return { data: result, error: null };
        } catch (error) {
            console.error('Google sign in error:', error);
            this.error = error;
            this.loading = false;
            this.notifyListeners();
            return { data: null, error };
        }
    }

    get isAuthenticated() {
        return !!this.user;
    }
}

// Create the global auth instance
let auth;

if (typeof window !== 'undefined' && window.FIREBASE_API_KEY && window.FIREBASE_AUTH_DOMAIN) {
    try {
        auth = new FirebaseAuth();
    } catch (error) {
        console.error('Error creating FirebaseAuth instance:', error);
        auth = new FirebaseAuth();
    }
} else {
    console.warn('Firebase credentials not available when auth.js loaded. Check server injection timing.');
    auth = new FirebaseAuth();
}

// Export auth globally
if (typeof window !== 'undefined') {
    window.auth = auth;
}