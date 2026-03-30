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
      launchAutoHide: true,
      autoHideDelay: 1500,
      backgroundColor: "#faf7f2",
      showSpinner: false,
    },
  },
};

export default config;
