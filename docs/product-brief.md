# Product brief

*Draft 1, 12 October 2026. Hisham + Claude. This page decides what we build; if a feature doesn't serve it, we don't build it yet.*

## In one sentence

We help Saudi trucking companies earn more from the trucks they already have, by planning the week so that fewer trucks drive home empty.

## Who it's for

- **Customer:** Saudi carriers with roughly 30–200 of their own trucks, doing intercity full-truckload work (one load fills one truck). For example: Dammam port → Riyadh, Jeddah → Madinah.
- **Buyer:** the owner or operations director. They care about revenue per truck and cost.
- **User:** the dispatcher, who today decides which truck does which load, usually with WhatsApp, Excel and memory.

## The problem

Freight in Saudi Arabia flows unevenly. Trucks go full into Riyadh and often come back empty, and every empty kilometre costs fuel and driver time and earns nothing. Worldwide, about 29% of truck kilometres are empty. In our own realistic 40-truck test, a simple planner drives **47% of kilometres empty**. Dispatchers can't weigh every combination of trucks, loads, return trips and driver rest in their heads, especially when the plan changes every day.

## What we promise

**More revenue per truck per week, with fewer empty kilometres, shown on the customer's own history before they pay.**

## How it works

1. **Bring the data in:** jobs, trucks and drivers, starting from the Excel files they already have.
2. **Plan the week:** assign every job to a truck and driver, respecting time windows, equipment and rest.
3. **Fill the empty legs:** suggest which extra or return loads to accept, and show what each one earns.
4. **Let the dispatcher steer:** they type changes in Arabic or English ("truck 12 must be in Dammam Thursday"), approve them, and the plan updates.
5. **Prove it:** replay their past weeks and show what they would have earned with our plan.

## How we'll know it works

| Measure | Why |
| --- | --- |
| Empty km % | The core problem. Pilot baseline today: 47% |
| Revenue per truck per day | What the owner pays for |
| Recommendations the dispatcher accepts | If they don't use it, nothing else matters |
| Planning time per day | The dispatcher's own win |

## What we're not doing now

A freight marketplace or brokerage, a driver mobile app, invoicing or a full TMS replacement, shared/partial loads (LTL), refrigerated or tanker rules, and automatic dispatch without a human approving it.

## Riskiest assumptions (to test with real carriers, not code)

1. Carriers can actually find return loads, from their own customers or spot platforms, if they know where trucks will be.
2. A carrier will share a few months of job and truck history with us.
3. The dispatcher has the authority to change assignments, and will trust a suggestion.
4. The gain is big enough to pay for. A rough anchor from our synthetic data: about SAR 80k revenue per truck per month, so a 5% gain ≈ SAR 4k per truck per month. *That figure comes from synthetic data, not a real carrier.*

## Milestones

1. The new engine beats today's planner on the pilot: fewer empty km, same jobs served.
2. It plans 100 trucks for a full week, with driver rest, in under a minute.
3. **The first carrier shares data**, and we show them the replay.

## Open decisions (Hisham)

- **Price:** per truck per month? (Hypothesis: SAR 400–800, roughly 10–20% of the value created.)
- **First region:** Eastern Province (Dammam/Jubail → Riyadh) looks like the clearest empty-return story.
- **Name:** "Madar" was a working name only.
- **First conversations:** which carriers can you reach?
