// supabaseClient.js
// 1) Create a Supabase project and paste values below:
const SUPABASE_URL = "PASTE_YOUR_SUPABASE_URL";
const SUPABASE_ANON_KEY = "PASTE_YOUR_SUPABASE_ANON_KEY";

// Supabase JS v2 must be loaded before this file.
window.supabaseClient = supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);