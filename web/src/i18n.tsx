// English / Arabic. Arabic switches the whole page to right-to-left.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Language = "en" | "ar";

const STRINGS = {
  en: {
    appName: "Madar",
    tagline: "Freight planning",
    email: "Email",
    password: "Password",
    signIn: "Sign in",
    signingIn: "Signing in…",
    signOut: "Sign out",
    loginTitle: "Sign in to your planning room",
    loginLead: "Plan your fleet's next 48 hours, see every truck's day, and steer the plan in Arabic or English.",
    wrongLogin: "Wrong email or password.",
    networkError: "Cannot reach the server. Is the API running?",
    navOverview: "Overview",
    navBoard: "Plan board",
    navData: "Data",
    navRules: "Rules",
    navHistory: "History",
    workspace: "Workspace",
    language: "العربية",
    overviewTitle: "Today's operation",
    trucks: "Trucks",
    sites: "Sites",
    contractJobs: "Contract jobs",
    offers: "Spot and return offers",
    horizon: "Planning window",
    drivingRules: "Driving-hours rules",
    on: "On",
    off: "Off",
    recentPlans: "Recent plans",
    noPlans: "No plans yet. Plans you run will appear here.",
    status: "Status",
    created: "Started",
    served: "Contract jobs served",
    emptyShare: "Empty km",
    contribution: "Contribution",
    valid: "Valid",
    statusQueued: "Queued",
    statusRunning: "Planning…",
    statusDone: "Done",
    statusFailed: "Failed",
    comingSoon: "Coming next",
    comingBoard: "Run a plan and see every truck's day on the timeline. (Step 3)",
    comingData: "Download templates and upload jobs and fleet from Excel or CSV. (Step 4)",
    comingRules: "Freeze work, add rules by form or in Arabic/English, ask why and what if. (Step 5)",
    comingHistory: "Compare plans and see what changed. (Step 6)",
    viewer: "Viewer",
    dispatcher: "Dispatcher",
    syntheticNote: "Demo company with synthetic data",
  },
  ar: {
    appName: "مدار",
    tagline: "تخطيط الشحن",
    email: "البريد الإلكتروني",
    password: "كلمة المرور",
    signIn: "تسجيل الدخول",
    signingIn: "جارٍ تسجيل الدخول…",
    signOut: "تسجيل الخروج",
    loginTitle: "سجّل الدخول إلى غرفة التخطيط",
    loginLead: "خطّط للساعات الـ48 القادمة لأسطولك، وتابع يوم كل شاحنة، ووجّه الخطة بالعربية أو الإنجليزية.",
    wrongLogin: "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
    networkError: "تعذّر الوصول إلى الخادم. هل واجهة البرمجة تعمل؟",
    navOverview: "نظرة عامة",
    navBoard: "لوحة الخطة",
    navData: "البيانات",
    navRules: "القواعد",
    navHistory: "السجل",
    workspace: "مساحة العمل",
    language: "English",
    overviewTitle: "العمليات اليوم",
    trucks: "الشاحنات",
    sites: "المواقع",
    contractJobs: "الشحنات المتعاقد عليها",
    offers: "الحمولات الفورية وحمولات العودة",
    horizon: "نافذة التخطيط",
    drivingRules: "قواعد ساعات القيادة",
    on: "مفعّلة",
    off: "غير مفعّلة",
    recentPlans: "أحدث الخطط",
    noPlans: "لا توجد خطط بعد. ستظهر هنا الخطط التي تشغّلها.",
    status: "الحالة",
    created: "بدأت",
    served: "الشحنات المنفذة",
    emptyShare: "كم بدون حمولة",
    contribution: "هامش المساهمة",
    valid: "صالحة",
    statusQueued: "في الانتظار",
    statusRunning: "جارٍ التخطيط…",
    statusDone: "اكتملت",
    statusFailed: "فشلت",
    comingSoon: "قريباً",
    comingBoard: "شغّل خطة وتابع يوم كل شاحنة على الخط الزمني. (الخطوة 3)",
    comingData: "نزّل القوالب وارفع الشحنات والأسطول من Excel أو CSV. (الخطوة 4)",
    comingRules: "جمّد الأعمال، وأضف قواعد بنموذج أو بالعربية والإنجليزية، واسأل لماذا وماذا لو. (الخطوة 5)",
    comingHistory: "قارن الخطط واعرف ما الذي تغيّر. (الخطوة 6)",
    viewer: "مشاهد",
    dispatcher: "مخطط رحلات",
    syntheticNote: "شركة تجريبية ببيانات اصطناعية",
  },
} as const;

export type StringKey = keyof (typeof STRINGS)["en"];

type I18n = {
  lang: Language;
  t: (key: StringKey) => string;
  toggle: () => void;
  number: (value: number, options?: Intl.NumberFormatOptions) => string;
  money: (minor: number | null | undefined) => string;
  date: (iso: string, options?: Intl.DateTimeFormatOptions) => string;
};

const Context = createContext<I18n | null>(null);

function initialLanguage(): Language {
  try {
    return localStorage.getItem("lang") === "ar" ? "ar" : "en";
  } catch {
    return "en";
  }
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Language>(initialLanguage);
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    try {
      localStorage.setItem("lang", lang);
    } catch {
      // private mode: language is simply not remembered
    }
  }, [lang]);
  const value = useMemo<I18n>(() => {
    // Western digits in both languages, common in Saudi business documents.
    const locale = lang === "ar" ? "ar-SA-u-nu-latn-ca-gregory" : "en-GB";
    return {
      lang,
      t: (key) => STRINGS[lang][key],
      toggle: () => setLang((current) => (current === "ar" ? "en" : "ar")),
      number: (value, options) => new Intl.NumberFormat(locale, options).format(value),
      money: (minor) => {
        if (minor === null || minor === undefined) return "—";
        const amount = new Intl.NumberFormat(locale).format(Math.round(minor / 100));
        return lang === "ar" ? `${amount} ريال` : `SAR ${amount}`;
      },
      date: (iso, options) =>
        new Intl.DateTimeFormat(locale, {
          timeZone: "Asia/Riyadh",
          dateStyle: "medium",
          timeStyle: "short",
          ...options,
        }).format(new Date(iso)),
    };
  }, [lang]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(Context);
  if (!value) throw new Error("useI18n outside I18nProvider");
  return value;
}
