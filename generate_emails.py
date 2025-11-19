import csv

EMAIL_TEMPLATE = """
{0}
{1} + TreeBites: Feed Students, not Trash Cans

Hi {1} team,

Got leftover food after your events? We're Stanford undergrads building TreeBites, an app that turns extra pizza into happy, fed students (instead of sad, lonely trash cans).

Snap a pic → Drop a pin → Students nearby get notified.
Zero waste and zero hassle.

Food gets eaten, students get fed, your event becomes instantly beloved.

Want to be one of our founding clubs? Join our early interest list (treebites.org): zero commitment, just first dibs and campus hero status!

Best,
TreeBites Team
"""

emails = []

with open("400-600.csv", "r") as f:
    reader = csv.reader(f)
    for row in reader:
        name, club = row

        if (name == "Email group officers"):
            continue
        
        email = EMAIL_TEMPLATE.format(name, club)
        emails.append(email)


with open('emails.txt', 'w') as f:
    for email in emails:
        f.write(email)
        f.write("\n---\n")