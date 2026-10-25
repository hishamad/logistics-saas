// A rule in plain words ("DMM-034 unavailable from … until …"), from the rule itself:
// what a dispatcher reads before adding a rule is exactly what the planner will get.
import type { Rule, Steering } from "../api";
import { useI18n } from "../i18n";

export type NewRule = Omit<Rule, "id" | "source_text"> & { source_text?: string };

export function useRuleText(steering: Steering | null) {
  const { fill, date, money, lang } = useI18n();
  return (rule: Rule | NewRule) => {
    if (!steering) return "";
    const team = steering.teams.find((t) => t.id === rule.team_id || t.tractor_id === rule.resource_id);
    const truck = team?.name ?? rule.resource_id ?? rule.team_id ?? "?";
    const job = steering.jobs.find((j) => j.id === rule.job_id)?.reference ?? rule.job_id ?? "?";
    const site = steering.sites.find((s) => s.id === rule.site_id);
    const siteName = site ? (lang === "ar" && site.name_ar ? site.name_ar : site.name) : (rule.site_id ?? "?");
    const when = (iso?: string) => (iso ? date(iso) : "?");
    switch (rule.kind) {
      case "resource_unavailable":
        return fill("descUnavailable", { truck, from: when(rule.window?.start), until: when(rule.window?.end) });
      case "required_end":
        return fill("descRequiredEnd", { truck, site: siteName, by: when(rule.window?.end) });
      case "customer_eligibility":
        return fill("descCustomer", { truck, customer: rule.customer ?? "?" });
      case "preferred_assignment":
        return rule.strength === "soft"
          ? fill("descAssignSoft", { job, truck, penalty: money(rule.penalty_minor) })
          : fill("descAssignHard", { job, truck });
    }
  };
}
