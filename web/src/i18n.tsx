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
    boardTitle: "Plan board",
    runPlan: "Run plan",
    depth: "Search depth",
    depthQuick: "Quick (15 s)",
    depthStandard: "Standard (30 s)",
    depthThorough: "Thorough (60 s)",
    planning: "The engine is planning",
    secondsShort: "s",
    noPlanYet: "No plan yet. Run the engine to plan your fleet.",
    viewerCannotPlan: "Viewers can look at plans but not run them.",
    planFailed: "The engine could not finish this plan.",
    passed: "Passed every check",
    findingsLabel: "Check findings",
    kServed: "Contract jobs served",
    kOffers: "Spot loads taken",
    kEmpty: "Driving empty",
    kPerTruck: "Revenue per truck-day",
    kContribution: "Contribution",
    kCost: "Modeled cost",
    of: "of",
    search: "Search truck, job, customer or site",
    allDepots: "All depots",
    sortDepot: "By depot",
    sortEmpty: "Most empty km",
    sortRevenue: "Most revenue",
    sortIdle: "Fewest jobs",
    week: "Week",
    detail: "Detail",
    legendLoaded: "Loaded",
    legendOffer: "Spot load",
    legendEmpty: "Empty",
    legendHandling: "Loading / unloading",
    legendWaiting: "Waiting",
    legendRest: "Rest / day off",
    nightNote: "Shaded = night (18:00–06:00 Riyadh)",
    trucksShown: "trucks shown",
    unservedTitle: "Unserved contract jobs",
    unservedNone: "Every contract job has a truck.",
    itinerary: "Itinerary",
    clickTruck: "Click a truck to see its itinerary.",
    colStart: "Start",
    colEnd: "End",
    colActivity: "Activity",
    colWhere: "Where",
    colKm: "km",
    colJob: "Job",
    actLoaded: "Loaded drive",
    actEmpty: "Empty drive",
    actLoading: "Loading",
    actUnloading: "Unloading",
    actTurnaround: "Turnaround",
    actWaiting: "Waiting",
    actRest: "Rest",
    customer: "Customer",
    price: "Price",
    load: "Load",
    jobsCount: "jobs",
    drivingHours: "h driving",
    kmLoaded: "km loaded",
    kmEmpty: "km empty",
    breaks: "breaks",
    rests: "overnight rests",
    planFrom: "Plan from",
    close: "Close",
    noMatches: "No trucks match these filters.",
    spot: "spot load",
    tonnes: "t",
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
    boardTitle: "لوحة الخطة",
    runPlan: "شغّل التخطيط",
    depth: "عمق البحث",
    depthQuick: "سريع (15 ث)",
    depthStandard: "عادي (30 ث)",
    depthThorough: "معمّق (60 ث)",
    planning: "المحرك يخطط الآن",
    secondsShort: "ث",
    noPlanYet: "لا توجد خطة بعد. شغّل المحرك لتخطيط أسطولك.",
    viewerCannotPlan: "يمكن للمشاهدين الاطلاع على الخطط دون تشغيلها.",
    planFailed: "تعذّر على المحرك إكمال هذه الخطة.",
    passed: "اجتازت جميع الفحوصات",
    findingsLabel: "ملاحظات التدقيق",
    kServed: "الشحنات المتعاقد عليها المنفذة",
    kOffers: "الحمولات الفورية المقبولة",
    kEmpty: "القيادة بدون حمولة",
    kPerTruck: "الإيراد لكل شاحنة يومياً",
    kContribution: "هامش المساهمة",
    kCost: "التكلفة التقديرية",
    of: "من",
    search: "ابحث عن شاحنة أو شحنة أو عميل أو موقع",
    allDepots: "كل المقار",
    sortDepot: "حسب المقر",
    sortEmpty: "الأكثر كم بدون حمولة",
    sortRevenue: "الأعلى إيراداً",
    sortIdle: "الأقل شحنات",
    week: "أسبوع",
    detail: "تفصيل",
    legendLoaded: "محمّلة",
    legendOffer: "حمولة فورية",
    legendEmpty: "فارغة",
    legendHandling: "تحميل / تفريغ",
    legendWaiting: "انتظار",
    legendRest: "راحة / إجازة",
    nightNote: "المظلل = الليل (18:00–06:00 بتوقيت الرياض)",
    trucksShown: "شاحنة معروضة",
    unservedTitle: "شحنات متعاقد عليها لم تُنفذ",
    unservedNone: "كل الشحنات المتعاقد عليها لها شاحنة.",
    itinerary: "مسار الرحلة",
    clickTruck: "اضغط على شاحنة لعرض مسار رحلتها.",
    colStart: "البداية",
    colEnd: "النهاية",
    colActivity: "النشاط",
    colWhere: "المكان",
    colKm: "كم",
    colJob: "الشحنة",
    actLoaded: "قيادة محمّلة",
    actEmpty: "قيادة فارغة",
    actLoading: "تحميل",
    actUnloading: "تفريغ",
    actTurnaround: "تجهيز",
    actWaiting: "انتظار",
    actRest: "راحة",
    customer: "العميل",
    price: "السعر",
    load: "الحمولة",
    jobsCount: "شحنات",
    drivingHours: "س قيادة",
    kmLoaded: "كم محمّلة",
    kmEmpty: "كم فارغة",
    breaks: "استراحات",
    rests: "راحات ليلية",
    planFrom: "خطة",
    close: "إغلاق",
    noMatches: "لا توجد شاحنات مطابقة لهذه المرشحات.",
    spot: "حمولة فورية",
    tonnes: "طن",
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
  span: (minutes: number) => string;
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
      span: (minutes) => {
        const [h, m] = [Math.floor(minutes / 60), Math.round(minutes % 60)];
        return lang === "ar" ? `${h} س ${m} د` : `${h}h ${m}m`;
      },
    };
  }, [lang]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(Context);
  if (!value) throw new Error("useI18n outside I18nProvider");
  return value;
}
