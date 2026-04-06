// src/pages/Login.jsx
import { SignIn } from "@clerk/clerk-react";

export default function Login() {
  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-app-bg flex items-center justify-center p-4">
      {/* Your Cyberpunk Background */}
      <div className="absolute inset-0 bg-grid-pattern z-0" />
      <div className="absolute top-[-100px] right-[-100px] w-[500px] h-[500px] rounded-full opacity-20 blur-[120px] bg-app-cyan pointer-events-none z-0" />
      <div className="absolute bottom-[-100px] left-[-100px] w-[400px] h-[400px] rounded-full opacity-10 blur-[100px] bg-app-pink pointer-events-none z-0" />

      {/* The Login Box */}
      <div className="relative z-10 animate-fade-up">
        {/* Clerk allows you to pass an "appearance" prop to style their component! */}
        <SignIn
          appearance={{
            elements: {
              card: "bg-[#0b0e1a]/80 backdrop-blur-md border border-app-cyan/30 shadow-[0_0_30px_rgba(0,240,255,0.05)]",
              headerTitle: "font-orbitron text-white tracking-widest",
              headerSubtitle: "text-white/50 font-dm",
              socialButtonsBlockButton:
                "border border-white/10 hover:bg-white/5 text-white transition-all",
              socialButtonsBlockButtonText: "font-dm font-bold text-white",
              dividerLine: "bg-white/10",
              dividerText: "text-white/40 font-dm",
              formFieldLabel:
                "text-white/60 font-orbitron uppercase text-xs tracking-widest",
              formFieldInput:
                "bg-[#0b0e1a]/50 border border-white/10 text-white focus:border-app-cyan focus:ring-1 focus:ring-app-cyan",
              formButtonPrimary:
                "bg-app-cyan/10 border border-app-cyan/40 hover:bg-app-cyan/20 text-app-cyan font-orbitron tracking-widest transition-all",
              footerActionText: "text-white/50",
              footerActionLink:
                "text-app-cyan hover:text-white transition-colors",
            },
          }}
        />
      </div>
    </div>
  );
}
