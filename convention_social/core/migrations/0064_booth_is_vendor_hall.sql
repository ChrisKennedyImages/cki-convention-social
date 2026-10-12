-- Chris, 2026-10-12: "Exhibition Halls, vendors and booths are all the same thing". One shot type from
-- here on; what the sorter and the final check had called a booth is the exhibition hall (vendor_hall).
UPDATE classifications SET shot_type = 'vendor_hall' WHERE shot_type = 'booth';
UPDATE final_checks SET shot_type = 'vendor_hall' WHERE shot_type = 'booth';
