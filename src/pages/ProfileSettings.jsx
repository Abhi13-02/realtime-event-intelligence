// src/pages/ProfileSettings.jsx
import { useEffect, useState } from "react";
import { usersApi } from "../services/users";

export default function ProfileSettings() {
  const [profile, setProfile] = useState({ name: "", phone_number: "" });
  const [loading, setLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState(null); 

  useEffect(() => {
    loadProfile();
  }, []);

  const loadProfile = async () => {
    try {
      setLoading(true);
      const data = await usersApi.getMe();
      setProfile({
        name: data.name || "",
        phone_number: data.phone_number || "",
      });
    } catch (error) {
      console.error("Failed to load profile:", error);
      setProfile({
        name: "Demo User",
        phone_number: "+1234567890",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setIsSaving(true);
    setSaveStatus(null);

    try {
      const payload = {};
      if (profile.name !== undefined) payload.name = profile.name;
      if (profile.phone_number !== undefined)
        payload.phone_number = profile.phone_number || null;

      await usersApi.updateMe(payload);
      setSaveStatus("success");

      setTimeout(() => setSaveStatus(null), 3000);
    } catch (error) {
      console.error("Failed to save profile:", error);
      setSaveStatus("error");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-10">
        <h1 className="text-3xl font-bold font-orbitron text-transparent bg-clip-text bg-gradient-to-r from-white to-white/70 tracking-wide">
          USER PROFILE
        </h1>
        <p className="text-white/50 mt-2 font-dm text-sm">
          Manage your personal identifiers and notification endpoints.
        </p>
      </div>

      {loading ? (
        <div className="text-center py-12 text-app-cyan font-orbitron tracking-widest animate-pulse">
          FETCHING USER DATA...
        </div>
      ) : (
        <div className="glass-card overflow-hidden animate-fade-up">
          <form onSubmit={handleSave} className="p-6 md:p-8 space-y-6">
            
            {/* Name Field */}
            <div>
              <label className="block text-xs font-orbitron tracking-widest text-white/60 mb-2 uppercase">
                Display Designation
              </label>
              <input
                type="text"
                value={profile.name}
                onChange={(e) =>
                  setProfile({ ...profile, name: e.target.value })
                }
                placeholder="Enter your handle..."
                className="w-full px-4 py-3 bg-[#0b0e1a]/50 border border-white/10 rounded-lg focus:border-app-cyan focus:ring-1 focus:ring-app-cyan outline-none text-white font-dm placeholder-white/20 transition-all"
              />
            </div>

            {/* Phone Number Field */}
            <div>
              <label className="block text-xs font-orbitron tracking-widest text-white/60 mb-2 uppercase">
                Secure Comm Link <span className="text-white/30 font-dm lowercase tracking-normal">(SMS routing)</span>
              </label>
              <input
                type="tel"
                value={profile.phone_number}
                onChange={(e) =>
                  setProfile({ ...profile, phone_number: e.target.value })
                }
                placeholder="+1 (555) 000-0000"
                className="w-full px-4 py-3 bg-[#0b0e1a]/50 border border-white/10 rounded-lg focus:border-app-cyan focus:ring-1 focus:ring-app-cyan outline-none text-white font-dm placeholder-white/20 transition-all"
              />
            </div>

            {/* Form Actions & Status Indicator */}
            <div className="pt-8 mt-4 border-t border-white/10 flex items-center justify-between">
              <div>
                {saveStatus === "success" && (
                  <span className="text-app-cyan font-orbitron text-xs tracking-widest uppercase flex items-center gap-2 animate-in fade-in">
                    <span className="w-2 h-2 rounded-full bg-app-cyan shadow-[0_0_8px_rgba(0,240,255,0.8)]"></span>
                    SYNC COMPLETE
                  </span>
                )}
                {saveStatus === "error" && (
                  <span className="text-app-pink font-orbitron text-xs tracking-widest uppercase flex items-center gap-2 animate-in fade-in">
                    <span className="w-2 h-2 rounded-full bg-app-pink shadow-[0_0_8px_rgba(255,0,127,0.8)]"></span>
                    SYNC FAILED
                  </span>
                )}
              </div>

              <button
                type="submit"
                disabled={isSaving}
                className="px-6 py-3 text-xs font-orbitron tracking-widest text-app-cyan bg-app-cyan/10 border border-app-cyan/40 hover:bg-app-cyan/20 disabled:opacity-30 disabled:cursor-not-allowed rounded-lg shadow-[0_0_15px_rgba(0,240,255,0.1)] transition-all flex items-center"
              >
                {isSaving ? "TRANSMITTING..." : "SAVE PARAMETERS"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}