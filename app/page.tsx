import { ArrowRight, Shield, Sparkles } from "lucide-react";
import { FaDiscord } from "react-icons/fa6";
import Link from "next/link";

export default function Home() {
  return (
    <main className="login-page">
      <section className="login-media">
        <div className="login-overlay" />
        <div className="quote">
          <Shield size={28} />
          <p>“Thanks to the help of CSRP Utilities, we've been able to add features specific to our server that no other bot could offer, like an advanced infractions system, fast staff management commands like /reinstate, and the addition of our smart hits system which automatically reviews hits and sends them for a secondary staff review.”</p>
          <span>- PointlessTalderson (Director)</span>
        </div>
      </section>
      <section className="login-panel">
        <div className="crumbs">
          <Link href="/">Home</Link>
          <span>/</span>
          <strong>Login</strong>
        </div>
        <div className="login-card">
          <img src="https://csrptickets-storage.s3.us-east-1.amazonaws.com/csrp.png" alt="CSRP Utilities Logo" width="120"/>
          <h1>Log in to CSRP Utilities</h1>
          <p>Sign in using your Discord account to continue.</p>
          <a className="button primary wide" href="/api/login">
            <FaDiscord size={18} />
            Continue with Discord
            <ArrowRight size={18} />
          </a>
        </div>
      </section>
    </main>
  );
}
