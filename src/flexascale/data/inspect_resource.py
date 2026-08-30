from flexascale.data.alibaba import load_resource_data


FILE = "data/raw/alibaba/v2021/MSResource_sample.csv"


def main():
    chunks = load_resource_data(FILE, chunksize=50_000)
    df = next(chunks)

    print("\n=== Shape ===")
    print(df.shape)

    print("\n=== Data types ===")
    print(df.dtypes)

    print("\n=== Missing values ===")
    print(df.isna().sum())

    print("\n=== Timestamp ===")
    print("Unique timestamps:", df["timestamp"].nunique())
    print("Min timestamp:", df["timestamp"].min())
    print("Max timestamp:", df["timestamp"].max())

    print("\n=== Services ===")
    print("Unique services:", df["msname"].nunique())

    print("\n=== Instances ===")
    print("Unique instances:", df["msinstanceid"].nunique())

    print("\n=== CPU ===")
    print(df["instance_cpu_usage"].describe())

    print("\n=== Memory ===")
    print(df["instance_memory_usage"].describe())

    print("\n=== Rows per timestamp ===")
    print(df.groupby("timestamp").size().head(20))

    print("\n=== Instances per service ===")
    print(
        df.groupby("msname")["msinstanceid"]
        .nunique()
        .describe()
    )


if __name__ == "__main__":
    main()
