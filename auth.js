// auth.js - Supabase Authentication Module
class SupabaseAuth {
    constructor() {
        // Initialize Supabase client
        // Get credentials from window (injected by server)
        this.supabaseUrl = window.SUPABASE_URL || '';
        this.supabaseAnonKey = window.SUPABASE_ANON_KEY || '';

        if (!this.supabaseUrl || !this.supabaseAnonKey) {
            console.error('Missing Supabase credentials. Please set SUPABASE_URL and SUPABASE_ANON_KEY.');
        }

        // Wait for supabase to be available
        if (typeof supabase === 'undefined') {
            console.error('Supabase library not loaded. Make sure @supabase/supabase-js is included before this script.');
            this.supabase = null;
        } else {
            const { createClient } = supabase;
            if (!this.supabaseUrl || !this.supabaseAnonKey) {
                console.error('Cannot create Supabase client: missing credentials');
                this.supabase = null;
            } else {
                try {
                    this.supabase = createClient(this.supabaseUrl, this.supabaseAnonKey);
                } catch (error) {
                    console.error('Error creating Supabase client:', error);
                    this.supabase = null;
                }
            }
        }

        this.user = null;
        this.session = null;
        this.loading = true;
        this.error = null;
        this.listeners = [];

        if (this.supabase) {
            this.init();
        } else {
            this.loading = false;
        }
    }

    init() {
        // Get initial session
        this.supabase.auth.getSession().then(({ data: { session }, error }) => {
            if (error) {
                console.error('Session error:', error);
                this.error = error;
            } else {
                this.session = session;
                this.user = session?.user ?? null;
            }
            this.loading = false;
            this.notifyListeners();
        });

        // Listen for auth changes
        this.supabase.auth.onAuthStateChange((_event, session) => {
            this.session = session;
            this.user = session?.user ?? null;
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
        this.loading = true;
        this.error = null;

        const { data, error } = await this.supabase.auth.signUp({
            email,
            password,
        });

        if (error) {
            console.error('Sign up error:', error);
            this.error = error;
        }

        this.loading = false;
        this.notifyListeners();
        return { data, error };
    }

    async signIn(email, password) {
        if (!this.supabase) {
            return { data: null, error: { message: 'Supabase client not initialized' } };
        }

        this.loading = true;
        this.error = null;

        try {
            const { data, error } = await this.supabase.auth.signInWithPassword({
                email,
                password,
            });

            if (error) {
                console.error('Sign in error:', error);
                this.error = error;
            }

            this.loading = false;
            this.notifyListeners();
            return { data, error };
        } catch (err) {
            this.loading = false;
            this.error = err;
            this.notifyListeners();
            return { data: null, error: err };
        }
    }

    async signOut() {
        this.loading = true;
        this.error = null;

        const { error } = await this.supabase.auth.signOut();

        if (error) {
            console.error('Sign out error:', error);
            this.error = error;
        }

        this.loading = false;
        this.notifyListeners();
        return { error };
    }

    async signInWithGoogle() {
        this.loading = true;
        this.error = null;

        if (!this.supabase) {
            const error = { message: 'Supabase not initialized' };
            this.error = error;
            this.loading = false;
            this.notifyListeners();
            return { data: null, error };
        }

        try {
            const { data, error } = await this.supabase.auth.signInWithOAuth({
                provider: 'google',
                options: {
                    redirectTo: `${window.location.origin}/index.html`
                }
            });

            if (error) {
                console.error('Google sign in error:', error);
                this.error = error;
                this.loading = false;
                this.notifyListeners();
            }
            // Note: OAuth redirects, so we don't set loading to false here

            return { data, error };
        } catch (err) {
            this.loading = false;
            this.error = err;
            this.notifyListeners();
            return { data: null, error: err };
        }
    }

    get isAuthenticated() {
        return !!this.user;
    }
}

// Create global auth instance - wait for credentials to be available
function createAuthInstance() {
    if (window.SUPABASE_URL && window.SUPABASE_ANON_KEY) {
        if (!window.auth) {
            window.auth = new SupabaseAuth();
        }
        return window.auth;
    }
    return null;
}

// Try to create immediately
let auth = createAuthInstance();

// If credentials not available, wait and retry
if (!auth) {
    let attempts = 0;
    const maxAttempts = 20;

    const retryAuth = setInterval(() => {
        attempts++;
        auth = createAuthInstance();

        if (auth) {
            clearInterval(retryAuth);
        } else if (attempts >= maxAttempts) {
            console.error('Credentials not available. Make sure server is injecting credentials into HTML.');
            clearInterval(retryAuth);
            // Create a dummy auth instance to prevent errors
            window.auth = new SupabaseAuth();
            auth = window.auth;
        }
    }, 100);
}

// Export auth
if (typeof window !== 'undefined') {
    window.auth = auth || window.auth;
}
