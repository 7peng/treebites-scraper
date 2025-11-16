import csv

names_list = []
with open("contacts.csv", "r") as f:
    reader = csv.reader(f)
    for row in reader:
        if row[0] != "Email group officers":
            names_list.append(row[0])
        else: pass

out_string = ", ".join(names_list)

with open("output.txt", "w") as output:
    output.write(out_string)