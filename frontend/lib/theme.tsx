"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

export type ThemeName = "dark" | "light";

interface ThemeState {
  theme: ThemeName;
  accentHue: number; // 150–300
  density: number; // 1–5
  radius: number; // 0–16 px
}

interface ThemeContextValue extends ThemeState {
  setTheme: (t: ThemeName) => void;
  setAccentHue: (h: number) => void;
  setDensity: (d: number) => void;
  setRadius: (r: number) => void;
}

const DEFAULTS: ThemeState = { theme: "dark", accentHue: 255, density: 4, radius: 8 };

// density level → [gap, pad] px (1 Airy … 5 Dense)
const DENSITY_GAP = [16, 14, 12, 10, 8];
const DENSITY_PAD = [20, 18, 16, 14, 11];
export const DENSITY_LABELS = ["Airy", "Comfortable", "Default", "Compact", "Dense"];

const STORAGE_KEY = "ni-theme";

const ThemeContext = createContext<ThemeContextValue>({
  ...DEFAULTS,
  setTheme: () => {},
  setAccentHue: () => {},
  setDensity: () => {},
  setRadius: () => {},
});

function apply(state: ThemeState) {
  const root = document.documentElement;
  root.dataset.theme = state.theme;
  root.style.setProperty("--hue", String(state.accentHue));
  root.style.setProperty("--radius", `${state.radius}px`);
  root.style.setProperty("--radiussm", `${Math.round(state.radius * 0.6)}px`);
  root.style.setProperty("--radiuslg", `${Math.round(state.radius * 1.5)}px`);
  root.style.setProperty("--gap", `${DENSITY_GAP[state.density - 1]}px`);
  root.style.setProperty("--pad", `${DENSITY_PAD[state.density - 1]}px`);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ThemeState>(DEFAULTS);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const saved = { ...DEFAULTS, ...JSON.parse(raw) } as ThemeState;
        setState(saved);
        apply(saved);
        return;
      }
    } catch {
      // corrupted storage — fall through to defaults
    }
    apply(DEFAULTS);
  }, []);

  const update = useCallback((patch: Partial<ThemeState>) => {
    setState((prev) => {
      const next = { ...prev, ...patch };
      apply(next);
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // storage full/blocked — theme still applies for this session
      }
      return next;
    });
  }, []);

  return (
    <ThemeContext.Provider
      value={{
        ...state,
        setTheme: (theme) => update({ theme }),
        setAccentHue: (accentHue) => update({ accentHue }),
        setDensity: (density) => update({ density }),
        setRadius: (radius) => update({ radius }),
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
