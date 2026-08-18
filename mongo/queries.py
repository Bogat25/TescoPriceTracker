FULL_PRODUCT_QUERY = """
query GetProduct($tpnc: String) {
  product(tpnc: $tpnc) {
    id
    tpnb
    gtin
    barcode
    title
    shortDescription
    brandName
    subBrand
    defaultImageUrl
    productType
    isNew
    isForSale
    status
    sellType
    superDepartmentName
    superDepartmentId
    departmentName
    departmentId
    aisleName
    aisleId
    shelfName
    shelfId
    primaryTaxonomyNode {
      id
      name
    }
    manufacturer {
      addresses
    }
    manufacturerAddress {
      name
      addressLine1
      addressLine2
      city
      postcode
    }
    distributorAddress {
      name
      addressLine1
      addressLine2
      city
      postcode
    }
    importerAddress {
      name
      addressLine1
      addressLine2
      city
      postcode
    }
    returnTo {
      name
      addressLine1
      addressLine2
      city
      postcode
    }
    depositAmount
    maxWeight
    minWeight
    storageClassification
    ... on ProductType {
      maxQuantityAllowed
    }
    displayImages {
      url
      default
    }
    details {
      packSize {
        value
        units
      }
      ingredients
      allergens {
        name
        values
      }
      nutrition {
        name
        value1
        value2
        value3
        value4
      }
      gda {
        name
        value
        percent
        rating
      }
      storage
      preparationAndUsage
      preparationGuidelines
      marketing
      productMarketing
      brandMarketing
      manufacturerMarketing
      originInformation {
        title
        value
      }
      recyclingInfo
      netContents
      drainedWeight
      safetyWarning
      lowerAgeLimit
      upperAgeLimit
      healthmark
      numberOfUses
      freezingInstructions {
        standardGuidelines
        freezingGuidelines
        defrosting
      }
      alcohol {
        grapeVariety
        storageType
        percentageAlcohol
        regionOfOrigin
        alcoholType
        wineColour
        alcoholUnits
        producer
        country
        legalNotice {
          message
          link
        }
      }
      dosage
      directions
      features
      healthClaims
      nutritionalClaims
      boxContents
      legalNotice
      shelfLifeInfo {
        hasShelfLife
        inStoreShelfLife
        depotShelLife
        customerShelfLife
      }
      otherInformation
      warnings
      additives
      dietaryInfo {
        includes
        excludes
      }
      intoleranceInfo {
        includes {
          category
          subCategory
        }
        excludes {
          category
          subCategory
        }
      }
      hfss {
        type
        score
        category
        indicator
      }
    }
    icons {
      id
      caption
      url
      type
      customerFacing
    }
    shelfLife {
      url
      message
    }
    reviews {
      stats {
        overallRating
        noOfReviews
        overallRatingRange
        ratingsDistribution {
          name
          value
        }
      }
    }
    price {
      actual
      unitPrice
      unitOfMeasure
    }
    promotions {
      id
      startDate
      endDate
      description
      attributes
      price {
        afterDiscount
      }
    }
  }
}
"""

PRICE_ONLY_QUERY = """
query GetProductPrice($tpnc: String) {
  product(tpnc: $tpnc) {
    id
    price {
      actual
      unitPrice
      unitOfMeasure
    }
    promotions {
      id
      startDate
      endDate
      description
      attributes
      price {
        afterDiscount
      }
    }
  }
}
"""
