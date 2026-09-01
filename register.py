# Stage 0: guard registers a patient before the call. Prints the session id.

import session_manager


def main():
    print("--- Patient registration ---")
    name = input("Name: ").strip()
    age = input("Age: ").strip()
    uhid = input("UHID: ").strip()
    phone = input("Phone number: ").strip()

    data = session_manager.new_session(name, age, uhid, phone)
    print()
    print(f"Session created: {data['session_id']}")
    print(f"Phone on file:   {data['phone']}")
    print("Ask the patient to call from this number.")


if __name__ == "__main__":
    main()
