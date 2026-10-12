"use client";

import { useEffect, useId, useRef } from "react";
import { X } from "lucide-react";
import { useLocale } from "@/lib/locale";

export function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: React.ReactNode;
  close: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const { t } = useLocale();
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby={titleId}
      onCancel={close}
      onClick={(e) => {
        if (e.target === ref.current) close();
      }}
    >
      <div className="modal-head">
        <h2 id={titleId}>{title}</h2>
        <button
          className="icon-button"
          aria-label={t("Close", "إغلاق")}
          onClick={close}
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad";
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function RevisionNotice({
  base,
  current,
}: {
  base: number;
  current: number;
}) {
  const { t } = useLocale();
  return base === current ? null : (
    <p className="notice warn">
      {t(
        "Inputs changed while this form was open. Close it and review the latest values before saving.",
        "تغيرت المدخلات أثناء فتح النموذج. أغلقه وراجع أحدث القيم قبل الحفظ.",
      )}
    </p>
  );
}

export function Empty({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-mark">↗</div>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
