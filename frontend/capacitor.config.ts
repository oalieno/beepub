import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.beepub.app",
  appName: "BeePub",
  webDir: "build",
  plugins: {
    Keyboard: {
      // Hide the accessory bar (prev/next/done) above the keyboard
      hideAccessoryBar: true,
    },
    SplashScreen: {
      // Plain cream: the web intro (SplashIntro) hides this as soon as it
      // is on screen; the delay is only a fallback.
      launchAutoHide: true,
      autoHideDelay: 3000,
      backgroundColor: "#faf7f2",
      showSpinner: false,
    },
  },
};

export default config;
