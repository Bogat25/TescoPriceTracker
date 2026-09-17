// Creates one MongoDB account per service, so no application connects as root.
//
// Run with the root account on every deploy (the `mongo-users` service in
// docker-compose.yml). It is idempotent: an account that exists has its roles
// and password reset to what this file says, so rotating a password in
// Infisical is enough. A service whose password is not set is skipped, which
// keeps a half-finished rollout working on the previous credentials.
//
// Rights follow what each service actually does:
//   api         reads the catalogue, writes cached statistics and the registry;
//               reads alerts for recommendations
//   scraper     writes the catalogue (Tesco and Auchan schedulers, vectorizer)
//   alerts      owns the alert database, reads the catalogue for price drops

const appDb = process.env.MONGO_DB_NAME || "tesco_tracker";
const alertsDb = process.env.MONGO_ALERTS_DB_NAME || "tesco_alerts";

const accounts = [
  {
    user: process.env.MONGO_API_USERNAME || "svc_api",
    password: process.env.MONGO_API_PASSWORD,
    roles: [
      { role: "readWrite", db: appDb },
      { role: "read", db: alertsDb },
    ],
  },
  {
    user: process.env.MONGO_SCRAPER_USERNAME || "svc_scraper",
    password: process.env.MONGO_SCRAPER_PASSWORD,
    roles: [{ role: "readWrite", db: appDb }],
  },
  {
    user: process.env.MONGO_ALERTS_USERNAME || "svc_alerts",
    password: process.env.MONGO_ALERTS_PASSWORD,
    roles: [
      { role: "readWrite", db: alertsDb },
      { role: "read", db: appDb },
    ],
  },
];

const admin = db.getSiblingDB("admin");
let created = 0;
let updated = 0;
let skipped = 0;

for (const account of accounts) {
  if (!account.password) {
    print(`skip ${account.user}: no password configured`);
    skipped += 1;
    continue;
  }
  const existing = admin.getUser(account.user);
  if (existing) {
    admin.updateUser(account.user, { pwd: account.password, roles: account.roles });
    print(`updated ${account.user}`);
    updated += 1;
  } else {
    admin.createUser({ user: account.user, pwd: account.password, roles: account.roles });
    print(`created ${account.user}`);
    created += 1;
  }
}

print(`mongo users: ${created} created, ${updated} updated, ${skipped} skipped`);
