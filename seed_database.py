"""
Populate / repair Supabase tables for the dashboard.
Run once:  python seed_database.py
"""
from DatabaseScript import supabase

FIRE_REGIONS = [
    ("FR1", "Περιφερειακή Πυροσβεστική Διοίκηση Ανατολικής Μακεδονίας και Θράκης"),
    ("FR2", "Περιφερειακή Πυροσβεστική Διοίκηση Κεντρικής Μακεδονίας"),
    ("FR3", "Περιφερειακή Πυροσβεστική Διοίκηση Δυτικής Μακεδονίας"),
    ("FR4", "Περιφερειακή Πυροσβεστική Διοίκηση Ηπείρου"),
    ("FR5", "Περιφερειακή Πυροσβεστική Διοίκηση Θεσσαλίας"),
    ("FR6", "Περιφερειακή Πυροσβεστική Διοίκηση Ιονίων Νήσων"),
    ("FR7", "Περιφερειακή Πυροσβεστική Διοίκηση Δυτικής Ελλάδας"),
    ("FR8", "Περιφερειακή Πυροσβεστική Διοίκηση Στερεάς Ελλάδας"),
    ("FR9", "Περιφερειακή Πυροσβεστική Διοίκηση Πελοποννήσου"),
    ("FR10", "Περιφερειακή Πυροσβεστική Διοίκηση Αττικής"),
    ("FR11", "Περιφερειακή Πυροσβεστική Διοίκηση Βορείου Αιγαίου"),
    ("FR12", "Περιφερειακή Πυροσβεστική Διοίκηση Νοτίου Αιγαίου"),
    ("FR13", "Περιφερειακή Πυροσβεστική Διοίκηση Κρήτης"),
]

DRONES = [
    ("DRONE_FR1_01", "ΣΜΗΕΑ Αμυγδαλεώνας", "DJI Matrice 30T", "active", 40.97, 24.37, 2.5, "FR1"),
    ("DRONE_FR1_02", "ΣΜΗΕΑ Χρυσούπολη", "Autel EVO Max", "active", 40.995, 24.7, 2.0, "FR1"),
    ("DRONE_FR1_03", "ΣΜΗΕΑ Καβάλας", "DJI Mavic 3T", "active", 40.94, 24.41, 1.8, "FR1"),
    ("DRONE_FR2_01", "ΣΜΗΕΑ Θεσσαλονίκης", "DJI Matrice 30T", "active", 40.64, 22.94, 3.0, "FR2"),
    ("DRONE_FR2_02", "ΣΜΗΕΑ Χαλκιδικής", "Autel EVO Max", "active", 40.32, 23.45, 2.5, "FR2"),
    ("DRONE_FR2_03", "ΣΜΗΕΑ Κατερίνης", "DJI Mavic 3T", "active", 40.27, 22.51, 2.0, "FR2"),
    ("DRONE_FR9_01", "ΣΜΗΕΑ Πάτρας", "DJI Matrice 30T", "active", 38.25, 21.73, 2.5, "FR9"),
    ("DRONE_FR9_02", "ΣΜΗΕΑ Τρίπολης", "Autel EVO Max", "active", 37.51, 22.38, 2.0, "FR9"),
    ("DRONE_FR10_01", "ΣΜΗΕΑ Αθηνών", "DJI Matrice 30T", "active", 37.98, 23.73, 3.5, "FR10"),
    ("DRONE_FR10_02", "ΣΜΗΕΑ Πειραιά", "DJI Mavic 3T", "active", 37.94, 23.65, 2.0, "FR10"),
    ("DRONE_FR10_03", "ΣΜΗΕΑ Μαραθώνα", "Autel EVO Max", "active", 38.15, 23.96, 2.5, "FR10"),
    ("DRONE_FR13_01", "ΣΜΗΕΑ Ηρακλείου", "DJI Matrice 30T", "active", 35.34, 25.14, 2.5, "FR13"),
    ("DRONE_FR13_02", "ΣΜΗΕΑ Χανίων", "Autel EVO Max", "active", 35.51, 24.02, 2.0, "FR13"),
    ("DRONE_FR13_03", "ΣΜΗΕΑ Ρεθύμνου", "DJI Mavic 3T", "active", 35.37, 24.47, 1.8, "FR13"),
]

NODE_REGIONS = [
    ("N1", "FR1"), ("N2", "FR1"),
    ("N1_1", "FR1"), ("N1_2", "FR1"), ("N1_3", "FR1"),
    ("N2_1", "FR1"), ("N2_2", "FR1"),
]


def upsert(table, rows, on_conflict):
    if not rows:
        return
    supabase.table(table).upsert(rows, on_conflict=on_conflict).execute()


def main():
    print("Seeding fire_regions...")
    try:
        upsert("fire_regions", [{"region_id": r, "name": n} for r, n in FIRE_REGIONS], "region_id")
    except Exception as e:
        print("\nWRITE BLOCKED (Row Level Security).")
        print("Run Database/Migrate_Update_And_Insert.sql in Supabase SQL Editor instead.")
        print(f"Details: {e}\n")
        return

    print("Seeding drones + drone_regions...")
    drone_rows = []
    region_rows = []
    for drone_id, name, model, status, lat, lng, radius, region_id in DRONES:
        drone_rows.append({
            "drone_id": drone_id,
            "name": name,
            "model": model,
            "operational_status": status,
            "home_lat": lat,
            "home_lng": lng,
            "roam_radius_km": radius,
        })
        region_rows.append({"drone_id": drone_id, "region_id": region_id})
    upsert("drones", drone_rows, "drone_id")
    upsert("drone_regions", region_rows, "drone_id")

    print("Seeding node_regions...")
    upsert(
        "node_regions",
        [{"node_id": n, "region_id": r} for n, r in NODE_REGIONS],
        "node_id",
    )

    dr = supabase.table("drone_regions").select("region_id", count="exact").execute()
    nr = supabase.table("node_regions").select("region_id", count="exact").execute()
    print(f"Done. drone_regions rows: {dr.count}, node_regions rows: {nr.count}")
    print("Restart App_test.py and log in again (logout first to clear session).")


if __name__ == "__main__":
    main()
