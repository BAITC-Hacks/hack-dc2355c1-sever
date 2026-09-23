"""Моки действий из actions.json поверх mock_backend.json и формул knowledge_base.json.

Цены, возвраты и статусы считает код, а не LLM — модель не может «придумать» сумму.
Изменения живут в памяти процесса (копия mock_backend), новые id не пересекаются с существующими.
Ошибки — в формате кита: {"error": {"code": ..., "message": ...}}.
"""

import copy
import itertools
import re
from datetime import date, timedelta
from typing import Any

from .catalog import catalog

TODAY = date.fromisoformat(catalog.as_of_date)
KB = catalog.knowledge_base
PRODUCTS = KB.get("products", {})
PREFIX = {"ogpo": "OGPO", "casco": "CASCO", "travel": "TRVL", "property": "PROP", "accident": "NS", "dms": "DMS"}

# Страна → зона тарифа путешествий (KB описывает зоны словами; самые частые направления — явно).
ZONE_BY_COUNTRY = {
    **dict.fromkeys(["russia", "kyrgyzstan", "uzbekistan", "tajikistan", "armenia", "azerbaijan", "belarus", "moldova", "georgia", "россия", "грузия", "кыргызстан", "узбекистан"], "A"),
    **dict.fromkeys(["germany", "france", "italy", "spain", "czechia", "czech republic", "austria", "netherlands", "greece", "poland", "hungary", "uk", "united kingdom", "portugal", "switzerland", "finland", "schengen", "германия", "франция", "италия", "испания", "шенген", "чехия", "греция"], "B"),
    **dict.fromkeys(["usa", "united states", "canada", "сша", "америка", "канада"], "D"),
}


SPECIALTY_SYNONYMS = {"терапевт": "therapist", "лор": "ENT", "ent": "ENT", "стоматолог": "dentist", "зубн": "dentist",
                      "гинеколог": "gynecologist", "кардиолог": "cardiologist", "анализ": "lab", "лаборат": "lab",
                      "тіс": "dentist", "дәрігер": "therapist"}
CLAIM_PRODUCT = {"ogpo": "ogpo", "casco": "casco", "property": "property", "travel": "travel", "accident": "accident"}
VEHICLE_SYNONYMS = {"легков": "car", "машин": "car", "жеңіл": "car", "грузов": "truck", "жүк": "truck", "мото": "motorcycle"}


class Backend:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        db = copy.deepcopy(catalog.mock_backend)
        self.clients: list[dict] = db.get("clients", [])
        self.policies: list[dict] = db.get("policies", [])
        self.claims: list[dict] = db.get("claims", [])
        self.payments: list[dict] = db.get("payments", [])
        self.default_bm = db.get("defaults", {}).get("unknown_iin_bm_class", "3")
        top = lambda items, key, rx: max((int(m.group(1)) for x in items if (m := re.search(rx, str(x.get(key, ""))))), default=0)
        # Отдельный счётчик на продукт: новый номер не пересекается с существующими этого продукта.
        self._policy_seq = {
            prod: itertools.count(top(self.policies, "policy_number", rf"SQ-{pref}-(\d{{6}})$") + 1 or 100001)
            for prod, pref in PREFIX.items()
        }
        self._claim_seq = itertools.count(top(self.claims, "claim_number", r"CL-(\d+)") + 12)
        self._ticket_seq = itertools.count(700118)
        self._fraud_seq = itertools.count(900044)
        self._dispute_seq = itertools.count(800021)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def err(code: str, message: str) -> dict:
        return {"error": {"code": code, "message": message}}

    @staticmethod
    def _phone(v: Any) -> str | None:
        digits = re.sub(r"\D", "", str(v or ""))
        if len(digits) == 11 and digits[0] in "78":
            return "+7" + digits[1:]
        if len(digits) == 10:
            return "+7" + digits
        return None

    def _client(self, client_id: str | None) -> dict | None:
        return next((c for c in self.clients if c["client_id"] == client_id), None)

    def _policy(self, number: str | None = None, plate: str | None = None) -> dict | None:
        plate = re.sub(r"\s", "", str(plate or "")).upper()
        for p in self.policies:
            if number and p["policy_number"].upper() == str(number).upper():
                return p
            if plate and p.get("details", {}).get("vehicle_plate", "").upper() == plate:
                return p
        return None

    @staticmethod
    def _status(p: dict) -> str:
        if p.get("status") in ("cancelled", "pending_payment"):
            return p["status"]
        start, end = date.fromisoformat(p["start_date"]), date.fromisoformat(p["end_date"])
        return "active" if start <= TODAY <= end else ("expired" if TODAY > end else "not_started")

    def _policy_view(self, p: dict) -> dict:
        return {
            "policy_number": p["policy_number"], "product": p["product"], "status": self._status(p),
            "start_date": p["start_date"], "end_date": p["end_date"], "premium": p.get("premium"),
            "details": p.get("details", {}),
        }

    def _bm(self, iin: str) -> str:
        c = next((c for c in self.clients if c.get("iin") == str(iin)), None)
        return str(c["bm_class"]) if c else str(self.default_bm)

    # ------------------------------------------------------------------ actions
    def find_client(self, phone: str | None = None, iin: str | None = None, **_) -> dict:
        if phone:
            norm = self._phone(phone)
            if not norm:
                return self.err("invalid_input", f"Phone {phone} is not a valid +7XXXXXXXXXX number")
            c = next((c for c in self.clients if c["phone"] == norm), None)
        elif iin:
            c = next((c for c in self.clients if c.get("iin") == str(iin)), None)
        else:
            return self.err("invalid_input", "phone or iin is required")
        if not c:
            return self.err("not_found", f"Client with {'phone ' + str(phone) if phone else 'IIN ' + str(iin)} not found")
        return {k: c[k] for k in ("client_id", "full_name", "city", "email", "preferred_language", "phone")}

    def get_policies(self, client_id: str, **_) -> dict:
        items = [self._policy_view(p) for p in self.policies if p["client_id"] == client_id]
        return {"policies": items} if items else self.err("not_found", f"No policies for {client_id}")

    def get_policy(self, policy_number: str | None = None, vehicle_plate: str | None = None, **_) -> dict:
        if not policy_number and not vehicle_plate:
            return self.err("invalid_input", "policy_number or vehicle_plate is required")
        p = self._policy(policy_number, vehicle_plate)
        return self._policy_view(p) if p else self.err("not_found", f"Policy {policy_number or vehicle_plate} not found")

    def get_bm_class(self, iin: str | list[str], **_) -> dict:
        iins = iin if isinstance(iin, list) else [iin]
        if any(not re.fullmatch(r"\d{12}", str(i)) for i in iins):
            return self.err("invalid_input", "IIN must be 12 digits")
        return {"bm_class": {str(i): self._bm(i) for i in iins}}

    def calc_ogpo_price(self, region: str | None = None, vehicle_type: str = "car", drivers_iin: list[str] | None = None,
                        term_months: int = 12, vehicle_plate: str | None = None, **_) -> dict:
        pr = PRODUCTS["ogpo"]["pricing"]
        if not region and vehicle_plate:
            code = re.sub(r"\s", "", vehicle_plate)[-2:]
            region = pr["region_by_plate_code"].get(code, pr["region_by_plate_code"]["default"])
        region = str(region or "").lower()
        region = {"алматы": "almaty", "астана": "astana"}.get(region, region)
        base = pr["base_by_region_kzt"].get(region, pr["base_by_region_kzt"]["other"])
        vtype = str(vehicle_type).lower()
        vtype = next((v for k, v in VEHICLE_SYNONYMS.items() if vtype.startswith(k)), vtype)
        vcoef = pr["vehicle_type_coef"].get(vtype)
        if vcoef is None:
            return self.err("invalid_input", f"vehicle_type must be one of {list(pr['vehicle_type_coef'])}")
        if not drivers_iin:
            return self.err("invalid_input", "drivers_iin is required (IIN of every driver)")
        classes = [self._bm(i) for i in drivers_iin]
        worst = max((pr["bm_coef"][c] for c in classes), default=1.0)  # худший класс = наибольший коэффициент
        tcoef = pr["term_coef"].get(str(term_months), 1.0)
        price = round(base * vcoef * worst * tcoef)
        return {"price": price, "region": region if region in pr["base_by_region_kzt"] else "other",
                "bm_classes": dict(zip(map(str, drivers_iin), classes)), "term_months": int(term_months)}

    def calc_casco_price(self, car_value: float, car_year: int, franchise: int = 0, package: str = "Standard", **_) -> dict:
        pr = PRODUCTS["casco"]["pricing"]
        age = TODAY.year - int(car_year)
        package = "Lite" if str(package).lower() == "lite" else "Standard"
        if age > pr["max_car_age"][package]:
            return self.err("not_eligible", f"Car is {age} years old, max for {package} is {pr['max_car_age'][package]}")
        rate = next(v for k, v in pr["rate_by_car_age"].items() if int(k.split("-")[0]) <= max(age, 0) <= int(k.split("-")[1])) \
            if age <= 10 else pr["rate_by_car_age"]["8-10"]
        fcoef = pr["franchise_coef"].get(str(int(franchise)))
        if fcoef is None:
            return self.err("invalid_input", f"franchise must be one of {list(pr['franchise_coef'])}")
        return {"price": round(float(car_value) * rate * fcoef * pr["package_coef"][package]), "car_age": age, "package": package}

    def calc_travel_price(self, trip_country: str, trip_start: str, trip_end: str, travelers_count: int = 1,
                          traveler_max_age: int = 30, zone: str | None = None, **_) -> dict:
        tr = PRODUCTS["travel"]
        if int(traveler_max_age) > 75:
            return self.err("not_eligible", "Travelers over 75 are insured only via an operator")
        zone = (zone or ZONE_BY_COUNTRY.get(str(trip_country).strip().lower(), "C")).upper()
        try:
            days = (date.fromisoformat(trip_end) - date.fromisoformat(trip_start)).days + 1
        except ValueError:
            return self.err("invalid_input", "trip_start/trip_end must be YYYY-MM-DD")
        if days <= 0:
            return self.err("invalid_input", "trip_end is before trip_start")
        age_coef = 2.0 if int(traveler_max_age) >= 65 else 1.0
        z = tr["zones"][zone]
        return {"price": round(z["rate_per_day_kzt"] * days * int(travelers_count) * age_coef), "zone": zone,
                "coverage": z["coverage"], "days": days}

    def calc_property_price(self, sum_insured: int, property_type: str = "apartment", **_) -> dict:
        table = PRODUCTS["property"]["price_per_year_kzt"]
        if str(int(sum_insured)) not in table:
            return self.err("invalid_input", f"sum_insured must be one of {list(table)}")
        coef = PRODUCTS["property"]["house_coef"] if str(property_type).lower() == "house" else 1.0
        return {"price": round(table[str(int(sum_insured))] * coef)}

    def calc_accident_price(self, sum_insured: int, **_) -> dict:
        table = PRODUCTS["accident"]["price_per_year_kzt"]
        if str(int(sum_insured)) not in table:
            return self.err("invalid_input", f"sum_insured must be one of {list(table)}")
        return {"price": table[str(int(sum_insured))]}

    def create_policy(self, product_type: str, phone: str, price: int | None = None, details: dict | None = None, **_) -> dict:
        product = str(product_type).lower()
        norm = self._phone(phone)
        if product not in PREFIX or not norm:
            return self.err("invalid_input", "product_type or phone is invalid")
        number = f"SQ-{PREFIX[product]}-{next(self._policy_seq[product])}"
        client = next((c for c in self.clients if c["phone"] == norm), None)
        self.policies.append({
            "policy_number": number, "client_id": client["client_id"] if client else None, "product": product,
            "start_date": TODAY.isoformat(), "end_date": (TODAY + timedelta(days=364)).isoformat(),
            "premium": price, "status": "pending_payment", "details": details or {},
        })
        return {"policy_number": number, "payment_link_sent_to": norm}

    def renew_policy(self, policy_number: str, **_) -> dict:
        p = self._policy(policy_number)
        if not p:
            return self.err("not_found", f"Policy {policy_number} not found")
        end = date.fromisoformat(p["end_date"])
        if (end - TODAY).days > 60:
            return self.err("not_eligible", f"Renewal opens 60 days before the end date ({p['end_date']})")
        number = f"SQ-{PREFIX[p['product']]}-{next(self._policy_seq[p['product']])}"
        self.policies.append({**copy.deepcopy(p), "policy_number": number, "start_date": (end + timedelta(days=1)).isoformat(),
                              "end_date": (end + timedelta(days=365)).isoformat(), "status": "pending_payment"})
        return {"policy_number": number, "price": p.get("premium"), "start_date": (end + timedelta(days=1)).isoformat()}

    def update_policy(self, policy_number: str, change: str | None = None, new_driver_iin: str | None = None,
                      new_vehicle_plate: str | None = None, **_) -> dict:
        p = self._policy(policy_number)
        if not p:
            return self.err("not_found", f"Policy {policy_number} not found")
        if self._status(p) != "active":
            return self.err("policy_inactive", f"Policy {policy_number} is {self._status(p)}")
        extra = 0
        if new_driver_iin and p["product"] == "ogpo":
            drivers = p["details"].get("drivers_iin", []) + [str(new_driver_iin)]
            new = self.calc_ogpo_price(vehicle_plate=p["details"].get("vehicle_plate"),
                                       vehicle_type=p["details"].get("vehicle_type", "car"), drivers_iin=drivers)
            if "error" in new:
                return new
            months_left = _full_months_between(TODAY, date.fromisoformat(p["end_date"]))
            extra = max(0, round((new["price"] - (p.get("premium") or 0)) * months_left / 12))
            p["details"]["drivers_iin"] = drivers
        if new_vehicle_plate:
            p["details"]["vehicle_plate"] = str(new_vehicle_plate).upper()
        return {"extra_premium": extra, "policy_number": p["policy_number"], "change": change or "updated"}

    def cancel_policy(self, policy_number: str, cancel_reason: str | None = None, **_) -> dict:
        p = self._policy(policy_number)
        if not p:
            return self.err("not_found", f"Policy {policy_number} not found")
        if p.get("status") == "cancelled":
            return self.err("already_done", f"Policy {policy_number} is already cancelled")
        if self._status(p) != "active":
            return self.err("policy_inactive", f"Policy {policy_number} is {self._status(p)}")
        if any(c["policy_number"] == p["policy_number"] and c["status"] == "paid" for c in self.claims):
            return self.err("not_eligible", "No refund: a claim was already paid under this policy")
        unused_months = _full_months_between(TODAY, date.fromisoformat(p["end_date"]))
        refund = round((p.get("premium") or 0) * unused_months / 12 * 0.9)
        p.update(status="cancelled", cancel_reason=cancel_reason)
        return {"refund_amount": refund, "unused_full_months": unused_months, "refund_time": KB["cancellation"]["refund_time"]}

    def create_claim(self, incident_date: str, incident_description: str, product_type: str | None = None,
                     policy_number: str | None = None, culprit_vehicle_plate: str | None = None, **_) -> dict:
        if culprit_vehicle_plate and not policy_number:
            p = self._policy(plate=culprit_vehicle_plate)
            if not p:
                return self.err("not_found", f"No Saqta policy for vehicle {culprit_vehicle_plate}")
            policy_number = p["policy_number"]
        if policy_number:
            p = self._policy(policy_number)
            if not p:
                return self.err("not_found", f"Policy {policy_number} not found")
            if self._status(p) != "active":
                return self.err("policy_inactive", f"Policy {policy_number} is {self._status(p)}")
        if not product_type:
            p = self._policy(policy_number) if policy_number else None
            product_type = CLAIM_PRODUCT.get(p["product"], "ogpo") if p else "ogpo"
        number = f"CL-{next(self._claim_seq)}"
        self.claims.append({"claim_number": number, "policy_number": policy_number, "claim_type": product_type,
                            "incident_date": incident_date, "status": "registered", "description": incident_description,
                            "next_step": "Upload the documents from the list sent by SMS."})
        docs_key = {"ogpo": "ogpo_victim"}.get(product_type, product_type)
        return {"claim_number": number, "documents": KB["claims"]["documents"].get(docs_key, []),
                "decision_time": KB["claims"]["decision_time"]}

    def get_claim(self, claim_number: str | None = None, client_id: str | None = None, **_) -> dict:
        items = [c for c in self.claims if (claim_number and c["claim_number"].upper() == str(claim_number).upper())
                 or (not claim_number and client_id and c.get("client_id") == client_id)]
        if not items:
            return self.err("not_found", f"Claim {claim_number or 'for ' + str(client_id)} not found")
        return items[0] if len(items) == 1 else {"claims": items}

    def create_dispute(self, claim_number: str, complaint_text: str, **_) -> dict:
        if not any(c["claim_number"].upper() == str(claim_number).upper() for c in self.claims):
            return self.err("not_found", f"Claim {claim_number} not found")
        return {"ticket_id": f"D-{next(self._dispute_seq)}", "review_time": KB["claims"]["dispute"]}

    def book_inspection(self, claim_number: str, city: str, preferred_date: str | None = None, **_) -> dict:
        if not any(c["claim_number"].upper() == str(claim_number).upper() for c in self.claims):
            return self.err("not_found", f"Claim {claim_number} not found")
        point = next((p for p in KB.get("inspection_points", []) if p["city"].lower() == str(city).lower()), None)
        if not point:
            cities = [p["city"] for p in KB.get("inspection_points", [])]
            return self.err("no_availability", f"No inspection point in {city}; available: {cities}")
        day = self._next_workday(preferred_date)
        return {"slot_datetime": f"{day} 10:00", "address": f"{point['city']}, {point['address']}", "hours": point["hours"]}

    def book_appointment(self, policy_number: str | None = None, doctor_specialty: str = "therapist", city: str | None = None,
                         preferred_date: str | None = None, client_id: str | None = None, **_) -> dict:
        p = self._policy(policy_number) if policy_number else next(
            (x for x in self.policies if x["client_id"] == client_id and x["product"] == "dms"), None)
        if not p or p["product"] != "dms":
            return self.err("not_found", "DMS policy not found")
        if self._status(p) != "active":
            return self.err("policy_inactive", f"Policy {p['policy_number']} is {self._status(p)}")
        spec = str(doctor_specialty).lower()
        spec = next((v for k, v in SPECIALTY_SYNONYMS.items() if spec.startswith(k)), spec).lower()
        if p["details"].get("package") == "Basic" and spec not in ("therapist", "lab"):
            return self.err("not_covered", "Basic package covers specialists only by therapist referral")
        city = city or (self._client(p["client_id"]) or {}).get("city")
        clinic = next((c for c in KB.get("clinics", []) if c["city"].lower() == str(city).lower() and spec in [s.lower() for s in c["specialties"]]), None)
        if not clinic:
            return self.err("no_availability", f"No partner clinic with {spec} in {city}")
        return {"clinic_name": clinic["name"], "address": clinic["address"], "slot_datetime": f"{self._next_workday(preferred_date)} 09:30",
                "policy_number": p["policy_number"]}

    def check_coverage(self, policy_number: str | None = None, service_name: str = "", client_id: str | None = None, **_) -> dict:
        p = self._policy(policy_number) if policy_number else next(
            (x for x in self.policies if x["client_id"] == client_id and x["product"] == "dms"), None)
        if not p:
            return self.err("not_found", "Policy not found")
        if self._status(p) != "active":
            return self.err("policy_inactive", f"Policy {p['policy_number']} is {self._status(p)}")
        pkg = PRODUCTS["dms"]["packages"].get(p["details"].get("package", "Basic"), {})
        return {"package": p["details"].get("package"), "service_asked": service_name,
                "covered_list": pkg.get("covered", []), "not_covered_list": pkg.get("not_covered", []),
                "note": "Decide coverage strictly from covered_list / not_covered_list."}

    def list_clinics(self, city: str, doctor_specialty: str | None = None, **_) -> dict:
        items = [c for c in KB.get("clinics", []) if c["city"].lower() == str(city).lower()
                 and (not doctor_specialty or str(doctor_specialty).lower() in [s.lower() for s in c["specialties"]])]
        return {"clinics": items} if items else self.err("not_found", f"No partner clinics in {city}")

    def resend_documents(self, policy_number: str | None = None, client_id: str | None = None, **_) -> dict:
        p = self._policy(policy_number) if policy_number else next((x for x in self.policies if x["client_id"] == client_id), None)
        if not p:
            return self.err("not_found", "Policy not found")
        c = self._client(p["client_id"]) or {}
        return {"policy_number": p["policy_number"], "sent_to": c.get("email"), "sms_to": c.get("phone")}

    def check_payment(self, client_id: str, payment_date: str | None = None, **_) -> dict:
        items = [x for x in self.payments if x["client_id"] == client_id and (not payment_date or x["date"] == payment_date)]
        items = items or [x for x in self.payments if x["client_id"] == client_id]
        if not items:
            return self.err("not_found", f"No payments for {client_id}" + (f" on {payment_date}" if payment_date else ""))
        x = items[-1]
        return {"payment_status": x["status"], "amount": x["amount"], "date": x["date"], "payment_id": x["payment_id"],
                "policy_number": x.get("policy_number"), "note": x.get("note")}

    def update_contact(self, client_id: str, contact_field: str, new_value: str, **_) -> dict:
        c = self._client(client_id)
        if not c:
            return self.err("not_found", f"Client {client_id} not found")
        field = {"email": "email", "phone": "phone", "address": "address"}.get(str(contact_field).lower())
        if not field:
            return self.err("invalid_input", "contact_field must be email, phone or address")
        if field == "phone":
            new_value = self._phone(new_value) or ""
            if not new_value:
                return self.err("invalid_input", "Phone must be +7XXXXXXXXXX")
        if field == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(new_value)):
            return self.err("invalid_input", "Email is not valid")
        c[field] = new_value
        return {"field": field, "new_value": new_value}

    def request_document(self, document_type: str, policy_number: str | None = None, email: str | None = None,
                         client_id: str | None = None, **_) -> dict:
        avail = KB.get("documents_available", {})
        if document_type not in avail:
            return self.err("invalid_input", f"document_type must be one of {list(avail)}")
        p = self._policy(policy_number) if policy_number else next((x for x in self.policies if x["client_id"] == client_id), None)
        if not p:
            return self.err("not_found", "Policy not found")
        to = email or (self._client(p["client_id"]) or {}).get("email")
        return {"sent_to": to, "delivery": avail[document_type], "policy_number": p["policy_number"]}

    def get_offices(self, city: str | None = None, **_) -> dict:
        items = [o for o in KB.get("offices", []) if not city or o["city"].lower() == str(city).lower()]
        return {"offices": items} if items else self.err("not_found", f"No office in {city}")

    def kb_lookup(self, topic: str, **_) -> dict:
        node: Any = KB
        for part in str(topic).replace("/", ".").split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                node = None
                break
        if node is not None:
            return {"answer": node}
        # Нечёткий поиск: разделы, в названии которых есть слово из запроса.
        words = [w for w in re.split(r"[\W_]+", str(topic).lower()) if len(w) > 2]
        hits = {f"{k}.{sub}" if sub else k: v for k, section in KB.items() if k != "meta"
                for sub, v in (section.items() if isinstance(section, dict) else [(None, section)])
                if any(w in (k + " " + (sub or "")).lower() for w in words)}
        if hits:
            return {"answer": hits}
        return self.err("not_found", f"Topic {topic} not found; top-level topics: {[k for k in KB if k != 'meta']}")

    def send_sms(self, phone: str, text: str | None = None, **_) -> dict:
        norm = self._phone(phone)
        return {"sent_to": norm} if norm else self.err("invalid_input", "Phone must be +7XXXXXXXXXX")

    def create_callback(self, phone: str, callback_time: str | None = None, **_) -> dict:
        norm = self._phone(phone)
        return {"phone": norm, "callback_time": callback_time or "в ближайший час"} if norm else self.err("invalid_input", "Phone must be +7XXXXXXXXXX")

    def create_complaint(self, complaint_text: str, **_) -> dict:
        return {"ticket_id": f"T-{next(self._ticket_seq)}", "review_time": KB.get("complaints", {}).get("review_time")}

    def report_fraud(self, fraud_details: str, **_) -> dict:
        return {"ticket_id": f"F-{next(self._fraud_seq)}"}

    def transfer_to_operator(self, queue: str = "operator_general", summary: str | None = None, **_) -> dict:
        queues = catalog.actions.get("queues", [])
        return {"queue": queue if queue in queues else "operator_general", "summary": summary}

    # ------------------------------------------------------------------
    @staticmethod
    def _next_workday(preferred: str | None) -> str:
        try:
            day = date.fromisoformat(preferred) if preferred else TODAY + timedelta(days=1)
        except ValueError:
            day = TODAY + timedelta(days=1)
        while day.weekday() == 6:
            day += timedelta(days=1)
        return day.isoformat()


def _full_months_between(start: date, end: date) -> int:
    """Число полных календарных месяцев, целиком лежащих в [start, end]."""
    cursor = start if start.day == 1 else (start.replace(day=1) + timedelta(days=32)).replace(day=1)
    months = 0
    while True:
        month_end = (cursor + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        if month_end > end:
            return min(months, 12)
        months += 1
        cursor = month_end + timedelta(days=1)


backend = Backend()
IRREVERSIBLE = {a["name"] for a in catalog.actions.get("actions", []) if a.get("irreversible")}


def call(name: str, args: dict, mode: str = "execute") -> dict:
    """mode=preview для необратимых действий: выполняем на копии состояния и выбрасываем изменения —
    клиент видит точный результат (сумму, номер), а в backend ничего не меняется до его «да»."""
    if name.startswith("_") or not callable(getattr(backend, name, None)):
        return Backend.err("invalid_input", f"Unknown action {name}")
    target = copy.deepcopy(backend) if mode == "preview" and name in IRREVERSIBLE else backend
    try:
        return getattr(target, name)(**args)
    except TypeError as e:
        missing = re.findall(r"'(\w+)'", str(e))
        return Backend.err("invalid_input", f"{name}: не хватает параметров {missing or str(e)} — собери их у клиента или выведи из разговора")
    except (ValueError, KeyError) as e:
        return Backend.err("invalid_input", str(e))

