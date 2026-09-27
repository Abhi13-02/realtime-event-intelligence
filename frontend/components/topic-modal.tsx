"use client";

// Create/Edit topic modal — handoff layout (name, description, sensitivity
// tiles).
//
// Delivery channels are not exposed: email digests and SMS are not wired up in
// this deployment, and offering a pill the alert path cannot honour is worse
// than offering nothing. Every topic is saved with the in-app ("websocket")
// channel only — see DEFAULT_CHANNELS below. The backend still stores channels
// per topic, so restoring the picker later is a UI-only change.

import { useEffect, useState } from "react";
import { Btn, Input, Label, Modal, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import type { DeliveryChannel, Topic } from "@/lib/types";

const DEFAULT_CHANNELS: DeliveryChannel[] = ["websocket"];

const SENSITIVITIES = [
  { id: "broad", label: "Broad", desc: "Fewer, larger clusters" },
  { id: "balanced", label: "Balanced", desc: "Recommended default" },
  { id: "high", label: "High", desc: "More, finer sub-themes" },
] as const;

export default function TopicModal({
  open,
  onClose,
  onSaved,
  topic,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  topic: Topic | null;
}) {
  const isEdit = !!topic;
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [sensitivity, setSensitivity] = useState<string>("balanced");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setError("");
    if (topic) {
      setName(topic.name);
      setDescription(topic.description ?? "");
      setSensitivity(topic.sensitivity ?? "balanced");
    } else {
      setName("");
      setDescription("");
      setSensitivity("balanced");
    }
  }, [open, topic]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const saved = isEdit
        ? await api.updateTopic(topic!.id, { name, description, sensitivity: sensitivity as Topic["sensitivity"] })
        : await api.createTopic({ name, description, sensitivity });
      await api.updateChannels(saved.id, DEFAULT_CHANNELS);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} maxWidth={480}>
      <div className="border-b border-line" style={{ padding: "18px 20px 14px" }}>
        <div className="text-ink" style={{ fontSize: 15, fontWeight: 600 }}>
          {isEdit ? "Edit topic" : "Track a new topic"}
        </div>
        <div className="text-mute" style={{ fontSize: 12, marginTop: 3 }}>
          {isEdit
            ? "Update how this topic is scoped."
            : "Discovery will begin its first pass after creation."}
        </div>
      </div>
      <form onSubmit={submit} style={{ padding: "18px 20px" }}>
        <Label>Topic name</Label>
        <Input
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Data Privacy Regulation"
          style={{ marginBottom: 15 }}
        />
        <Label>Description</Label>
        <Textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What should this topic capture? Sources, angles, entities to watch."
          style={{ marginBottom: 16 }}
        />
        <Label>Discovery sensitivity</Label>
        <div className="flex" style={{ gap: 8, marginBottom: 20 }}>
          {SENSITIVITIES.map((s) => {
            const active = sensitivity === s.id;
            return (
              <div
                key={s.id}
                onClick={() => setSensitivity(s.id)}
                className="flex-1 cursor-pointer transition-colors"
                style={{
                  padding: "10px 11px",
                  borderRadius: "var(--radius)",
                  border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
                  background: active ? "var(--accentsoft)" : "var(--bg2)",
                }}
              >
                <div className="text-ink" style={{ fontSize: 12, fontWeight: 600 }}>
                  {s.label}
                </div>
                <div className="text-mute" style={{ fontSize: 10, marginTop: 3, lineHeight: 1.3 }}>
                  {s.desc}
                </div>
              </div>
            );
          })}
        </div>
        {error && (
          <div className="text-neg" style={{ fontSize: 12, marginBottom: 10 }}>
            {error}
          </div>
        )}
        <div className="flex justify-end" style={{ gap: 9 }}>
          <Btn type="button" onClick={onClose} style={{ height: 33, padding: "0 15px" }}>
            Cancel
          </Btn>
          <Btn
            type="submit"
            variant="primary"
            disabled={submitting || !name.trim()}
            style={{ height: 33, padding: "0 17px" }}
          >
            {submitting ? "Saving…" : isEdit ? "Save changes" : "Create topic"}
          </Btn>
        </div>
      </form>
    </Modal>
  );
}
