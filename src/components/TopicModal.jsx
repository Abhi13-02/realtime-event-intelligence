// src/components/TopicModal.jsx
import { useState } from "react";
import { topicsApi } from "../services/topics";

export default function TopicModal({ isOpen, onClose, onSuccess }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedChannels, setSelectedChannels] = useState(["websocket"]);
  const [sensitivity, setSensitivity] = useState("balanced");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Change all IDs to match your FastAPI DeliveryChannel Enum exactly
  const availableChannels = [
    { id: "websocket", label: "In-App Feed" },
    { id: "email", label: "Email Digest" },
    { id: "sms", label: "SMS Alert" },
  ];

  const sensitivityLevels = [
    { id: "broad", label: "Broad", desc: "More hits, lower strictness" },
    { id: "balanced", label: "Balanced", desc: "Standard filter" },
    { id: "high", label: "High", desc: "Strict, high-quality only" },
  ];

  const toggleChannel = (channelId) => {
    setSelectedChannels((prev) =>
      prev.includes(channelId)
        ? prev.filter((c) => c !== channelId)
        : [...prev, channelId],
    );
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);

    try {
      const newTopic = await topicsApi.createTopic({
        name,
        description,
        sensitivity,
      });
      if (selectedChannels.length > 0) {
        await topicsApi.updateChannels(newTopic.id, selectedChannels);
      }
      setName("");
      setDescription("");
      setSelectedChannels(["websocket"]);
      setSensitivity("balanced");
      onSuccess();
      onClose();
    } catch (error) {
      console.error("Failed to create topic:", error);
      alert("System Error: Failed to init topic.");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#0b0e1a]/80 backdrop-blur-md">
      <div className="glass-card border border-app-cyan/30 shadow-[0_0_30px_rgba(0,240,255,0.05)] w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        <div className="px-6 py-5 border-b border-white/10 flex justify-between items-center bg-white/5">
          <h2 className="text-lg font-bold font-orbitron tracking-wider text-white">
            INIT NEW TOPIC
          </h2>
          <button
            onClick={onClose}
            className="text-white/40 hover:text-app-pink text-2xl leading-none transition-colors"
          >
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6">
          <div className="space-y-5">
            {/* Name Input */}
            <div>
              <label className="block text-xs font-orbitron tracking-widest text-white/60 mb-2 uppercase">
                Topic Designation
              </label>
              <input
                type="text"
                required
                placeholder="e.g., Artificial Intelligence"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-4 py-2.5 bg-[#0b0e1a]/50 border border-white/10 rounded-lg focus:border-app-cyan focus:ring-1 focus:ring-app-cyan outline-none text-white font-dm placeholder-white/20 transition-all"
              />
            </div>

            {/* Description Input */}
            <div>
              <label className="block text-xs font-orbitron tracking-widest text-white/60 mb-2 uppercase">
                Parameters (Optional)
              </label>
              <textarea
                rows="3"
                placeholder="What exactly are we tracking here?"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full px-4 py-2.5 bg-[#0b0e1a]/50 border border-white/10 rounded-lg focus:border-app-cyan focus:ring-1 focus:ring-app-cyan outline-none text-white font-dm placeholder-white/20 transition-all resize-none"
              />
            </div>

            {/* Channel Selection (Pills) */}
            <div>
              <label className="block text-xs font-orbitron tracking-widest text-white/60 mb-3 uppercase">
                Routing Channels
              </label>
              <div className="flex flex-wrap gap-2">
                {availableChannels.map((channel) => {
                  const isSelected = selectedChannels.includes(channel.id);
                  return (
                    <button
                      key={channel.id}
                      type="button"
                      onClick={() => toggleChannel(channel.id)}
                      className={`px-3 py-1.5 text-[10px] font-orbitron tracking-widest uppercase rounded border transition-all ${
                        isSelected
                          ? "bg-app-cyan/20 text-app-cyan border-app-cyan/50 shadow-[0_0_10px_rgba(0,240,255,0.1)]"
                          : "bg-white/5 text-white/50 border-white/10 hover:border-white/30 hover:text-white"
                      }`}
                    >
                      {channel.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Sensitivity Selection */}
            <div>
              <label className="block text-xs font-orbitron tracking-widest text-white/60 mb-3 uppercase">
                Matching Sensitivity
              </label>
              <div className="grid grid-cols-3 gap-2">
                {sensitivityLevels.map((level) => {
                  const isSelected = sensitivity === level.id;
                  return (
                    <button
                      key={level.id}
                      type="button"
                      onClick={() => setSensitivity(level.id)}
                      className={`flex flex-col items-center gap-1 px-2 py-2 rounded border transition-all ${
                        isSelected
                          ? "bg-app-purple/20 text-app-purple border-app-purple/50 shadow-[0_0_10px_rgba(157,78,221,0.1)]"
                          : "bg-white/5 text-white/40 border-white/10 hover:border-white/30"
                      }`}
                    >
                      <span className="text-[10px] font-orbitron tracking-widest uppercase font-bold">
                        {level.label}
                      </span>
                      <span className="text-[8px] leading-tight text-center opacity-60 font-dm">
                        {level.desc}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Form Actions */}
          <div className="mt-8 flex justify-end gap-3 pt-4 border-t border-white/10">
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 text-xs font-orbitron tracking-widest text-white/50 hover:bg-white/10 rounded-lg transition-colors"
            >
              ABORT
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !name.trim()}
              className="px-5 py-2.5 text-xs font-orbitron tracking-widest text-app-cyan bg-app-cyan/10 border border-app-cyan/40 hover:bg-app-cyan/20 disabled:opacity-30 disabled:cursor-not-allowed rounded-lg shadow-[0_0_15px_rgba(0,240,255,0.1)] transition-all flex items-center"
            >
              {isSubmitting ? "PROCESSING..." : "EXECUTE"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
